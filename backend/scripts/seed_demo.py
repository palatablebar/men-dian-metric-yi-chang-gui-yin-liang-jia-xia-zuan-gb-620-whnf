"""幂等 seed：3 账号 / 120 门店 / 32,400 指标点 / 1 次检测 / 37 起异常 + 归因 / 1 份周报。

自然键 upsert：
  users.email / stores.code / metric_points(store_id, stat_date, channel)
  runs.seed_key / anomalies(store_id, metric_date, metric_key) / attributions.anomaly_id
  reports.seed_key / audit_logs.seed_key
重复执行不新增、不覆盖用户改过的处理结论；SEED_SUMMARY 逐字一致。

口径：SEED_SUMMARY brand=<短名> users=<n> sources=<门店数> runs=<检测批次> findings=<异常数> pending=<待处理数>
（sources 在本项目对应「门店」，findings 对应「异常」）
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, insert, select

from src.config.database import session_scope
from src.models.anomaly import Anomaly
from src.models.attribution import Attribution
from src.models.audit import AuditLog
from src.models.metric import MetricPoint
from src.models.report import Report
from src.models.run import Run
from src.models.store import Store
from src.models.user import User
from src.services import attribution_service, report_service, run_service
from src.utils.logger import get_logger
from src.utils.security import hash_password

from scripts.demo_config import (
    DEMO_PASSWORD,
    DEMO_USERS,
    ORG,
    SEED_REPORT,
    SEED_REVIEWS,
    SEED_RUN,
)
from scripts.demo_data import build_dataset

logger = get_logger("seed")


def ensure_users(db) -> int:
    for email, display_name, role in DEMO_USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(DEMO_PASSWORD),
                    display_name=display_name,
                    role=role,
                    org=ORG,
                )
            )
    db.flush()
    return db.scalar(select(func.count()).select_from(User)) or 0


def ensure_stores(db, specs: list[dict]) -> dict[str, Store]:
    for spec in specs:
        store = db.scalar(select(Store).where(Store.code == spec["code"]))
        if store is None:
            store = Store(
                code=spec["code"],
                name=spec["name"],
                region=spec["region"],
                city=spec["city"],
                brand=spec["brand"],
                room_count=spec["room_count"],
                manager=spec["manager"],
                status=spec["status"],
                note=f"{spec['region']} · {spec['city']} · 房量 {spec['room_count']}",
            )
            db.add(store)
            db.flush()
    db.flush()
    return {store.code: store for store in db.scalars(select(Store)).all()}


def ensure_metrics(db, specs: list[dict], stores: dict[str, Store], points: list[dict]) -> int:
    existing = db.scalar(select(func.count()).select_from(MetricPoint)) or 0
    if existing:
        return existing
    rows = []
    for point in points:
        store = stores.get(point["store_code"])
        if store is None:
            continue
        rows.append(
            {
                "store_id": store.id,
                "stat_date": point["stat_date"],
                "channel": point["channel"],
                "rooms_available": point["rooms_available"],
                "rooms_sold": point["rooms_sold"],
                "occupancy": point["occupancy"],
                "adr": point["adr"],
                "revenue": point["revenue"],
                "is_weekend": point["is_weekend"],
                "room_type_mix": point["room_type_mix"],
            }
        )
    db.execute(insert(MetricPoint), rows)
    db.flush()
    return db.scalar(select(func.count()).select_from(MetricPoint)) or 0


def ensure_run(db) -> Run:
    return run_service.create_and_execute(
        db,
        store_id=None,
        trigger=SEED_RUN["trigger"],
        operator_email=SEED_RUN["operator"],
        params=SEED_RUN["params"],
        seed_key=SEED_RUN["seed_key"],
    )


def ensure_attributions(db) -> int:
    anomalies = db.scalars(select(Anomaly).order_by(Anomaly.id)).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    for anomaly in anomalies:
        attribution_service.build(db, anomaly, stores.get(anomaly.store_id))
    db.flush()
    return db.scalar(select(func.count()).select_from(Attribution)) or 0


def ensure_reviews(db) -> None:
    stores = {store.code: store for store in db.scalars(select(Store)).all()}
    for code, metric_date, status, note in SEED_REVIEWS:
        store = stores.get(code)
        if store is None:
            continue
        anomaly = db.scalar(
            select(Anomaly).where(
                Anomaly.store_id == store.id,
                Anomaly.metric_date == date.fromisoformat(metric_date),
                Anomaly.metric_key == "rev",
            )
        )
        if anomaly is None or anomaly.status != "pending":
            continue
        anomaly.status = status
        anomaly.reviewer = "analyst@anomalyattr.io"
        anomaly.review_note = note
        from src.utils.timeutil import utcnow

        anomaly.reviewed_at = utcnow()
    db.flush()


def ensure_report(db) -> int:
    existing = db.scalar(select(Report).where(Report.seed_key == SEED_REPORT["seed_key"]))
    if existing is None:
        report = report_service.generate(
            db,
            {
                "kind": SEED_REPORT["kind"],
                "period_start": SEED_REPORT["period_start"],
                "period_end": SEED_REPORT["period_end"],
                "note": "seed 预置周报：口径同 README §10",
            },
            "admin@anomalyattr.io",
        )
        report.title = SEED_REPORT["title"]
        report.seed_key = SEED_REPORT["seed_key"]
        report.status = SEED_REPORT["status"]
        db.flush()
    return db.scalar(select(func.count()).select_from(Report)) or 0


def ensure_audit(db) -> None:
    seeds = [
        ("seed-audit-1", "admin@anomalyattr.io", "admin", "store.create", "store", {"code": "LB-HD-001"}),
        ("seed-audit-2", "analyst@anomalyattr.io", "analyst", "run.create", "run", {"run": SEED_RUN["seed_key"]}),
        ("seed-audit-3", "admin@anomalyattr.io", "admin", "report.generate", "report", {"report": SEED_REPORT["seed_key"]}),
    ]
    for seed_key, email, role, action, entity, detail in seeds:
        exists = db.scalar(select(AuditLog).where(AuditLog.seed_key == seed_key))
        if exists is None:
            db.add(
                AuditLog(
                    actor_email=email,
                    actor_role=role,
                    action=action,
                    entity=entity,
                    detail=detail,
                    layer="seed",
                    seed_key=seed_key,
                )
            )
    db.flush()


def seed_all() -> dict:
    dataset = build_dataset()
    with session_scope() as db:
        users = ensure_users(db)
        stores = ensure_stores(db, dataset["stores"])
        ensure_metrics(db, dataset["stores"], stores, dataset["points"])
        run = ensure_run(db)
        ensure_attributions(db)
        ensure_reviews(db)
        ensure_report(db)
        ensure_audit(db)
        store_total = db.scalar(select(func.count()).select_from(Store)) or 0
        runs = db.scalar(select(func.count()).select_from(Run)) or 0
        findings = db.scalar(select(func.count()).select_from(Anomaly)) or 0
        pending = db.scalar(select(func.count()).select_from(Anomaly).where(Anomaly.status == "pending")) or 0
        summary = (
            f"SEED_SUMMARY brand=anomalyattr users={users} sources={store_total} "
            f"runs={runs} findings={findings} pending={pending}"
        )
        print(summary, flush=True)
        logger.info("seed run %s -> %s anomalies", run.run_no, run.anomaly_count)
        return {
            "users": users,
            "stores": store_total,
            "runs": runs,
            "findings": findings,
            "pending": pending,
            "run_no": run.run_no,
        }


if __name__ == "__main__":
    seed_all()
