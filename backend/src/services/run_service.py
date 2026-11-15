"""检测运行服务：加载序列 → 算法 A 检测 → 落异常 → 生成归因 → 汇总指标。"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import METRIC_LABELS
from src.models.anomaly import Anomaly
from src.models.metric import MetricPoint
from src.models.run import Run
from src.models.store import Store
from src.services import anomaly_service, attribution_service, detection, metric_service
from src.utils.errors import AppError
from src.utils.timeutil import iso_utc, local_now, utcnow

DEFAULT_PARAMS = {"metrics": ["rev"], "window": 28, "threshold": 3.5, "persist_z": 1.5, "stratify": True}


def serialize(run: Run, store_name: str | None = None) -> dict:
    return {
        "id": run.id,
        "run_no": run.run_no,
        "store_id": run.store_id,
        "store_name": store_name,
        "trigger": run.trigger,
        "status": run.status,
        "operator_email": run.operator_email,
        "store_count": run.store_count,
        "point_count": run.point_count,
        "anomaly_count": run.anomaly_count,
        "params": run.params or {},
        "metrics": run.metrics or {},
        "log_text": run.log_text,
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
    }


def next_run_no(db: Session) -> str:
    prefix = f"DT{local_now():%Y%m%d}"
    count = db.scalar(select(func.count()).select_from(Run).where(Run.run_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:04d}"


def _normalize_params(payload: dict | None) -> dict:
    params = dict(DEFAULT_PARAMS)
    for key, value in (payload or {}).items():
        if value is None:
            continue
        params[key] = value
    metrics = [item for item in params.get("metrics") or ["rev"] if item in METRIC_LABELS]
    params["metrics"] = metrics or ["rev"]
    return params


def execute(db: Session, run: Run) -> Run:
    run.status = "running"
    params = _normalize_params(run.params)
    run.params = params
    try:
        stores = db.scalars(select(Store).order_by(Store.code)).all()
        if run.store_id:
            stores = [store for store in stores if store.id == run.store_id]
        bounds = metric_service.date_bounds(db)
        grouped = metric_service.series_points(db, bounds[0], bounds[1], run.store_id)
        point_count = db.scalar(select(func.count()).select_from(MetricPoint)) or 0

        created = 0
        updated = 0
        hit_total = 0
        by_severity = {"high": 0, "medium": 0, "low": 0}
        by_metric: dict[str, int] = {}
        skipped_reasons: dict[str, int] = {}
        z_values: list[float] = []

        for store in stores:
            series = grouped.get(store.id)
            if not series:
                continue
            for metric_key in params["metrics"]:
                result = detection.detect_series(
                    series,
                    metric_key,
                    window=params["window"],
                    threshold=params["threshold"],
                    persist_z=params["persist_z"],
                    stratify=params["stratify"],
                )
                for reason in result["skipped"]:
                    skipped_reasons[reason["reason"]] = skipped_reasons.get(reason["reason"], 0) + 1
                for hit in result["hits"]:
                    payload = {
                        "store_id": store.id,
                        "metric_date": date.fromisoformat(hit["date"]),
                        "metric_key": metric_key,
                        "observed": hit["observed"],
                        "baseline": hit["baseline"],
                        "mad": hit["mad"],
                        "robust_z": hit["robust_z"],
                        "direction": hit["direction"],
                        "severity": hit["severity"],
                        "impact_amount": hit["impact_amount"],
                        "run_id": run.id,
                        "status": "pending",
                        "payload": {
                            "window_start": hit["window_start"],
                            "window_end": hit["window_end"],
                            "window_samples": hit["window_samples"],
                            "mad_basis": hit["mad_basis"],
                            "baseline_triple": hit["baseline_triple"],
                            "current_triple": hit["current_triple"],
                            "params": result["params"],
                        },
                    }
                    anomaly, is_new = anomaly_service.ensure_anomaly(db, payload)
                    created += 1 if is_new else 0
                    updated += 0 if is_new else 1
                    hit_total += 1
                    by_severity[anomaly.severity] = by_severity.get(anomaly.severity, 0) + 1
                    by_metric[metric_key] = by_metric.get(metric_key, 0) + 1
                    z_values.append(abs(anomaly.robust_z))
                    attribution_service.build(db, anomaly, store)

        impact_total = db.scalar(
            select(func.sum(Anomaly.impact_amount)).where(Anomaly.run_id == run.id)
        ) or 0.0
        run.store_count = len(stores)
        run.point_count = point_count
        run.anomaly_count = hit_total
        run.metrics = {
            "metrics": params["metrics"],
            "window": params["window"],
            "threshold": params["threshold"],
            "persist_z": params["persist_z"],
            "stores": len(stores),
            "points": point_count,
            "anomalies": hit_total,
            "created": created,
            "updated": updated,
            "severity": by_severity,
            "by_metric": by_metric,
            "impact_total": round(float(impact_total), 2),
            "max_abs_z": round(max(z_values), 4) if z_values else 0.0,
            "skipped": skipped_reasons,
        }
        run.status = "success" if created or updated else "partial"
        run.log_text = (
            f"检测 {len(stores)} 家门店 / {point_count} 条指标点；命中 {hit_total} 起异常"
            f"（新增 {created}、更新 {updated}）；high={by_severity.get('high', 0)}"
            f" medium={by_severity.get('medium', 0)} low={by_severity.get('low', 0)}；"
            f"影响合计 {float(impact_total):,.0f} 元。口径：window={params['window']} "
            f"threshold={params['threshold']} persist_z={params['persist_z']} 周末分层={params['stratify']}"
        )
    except Exception as exc:  # noqa: BLE001 - 运行失败要留痕，不抛 500
        run.status = "failed"
        run.log_text = f"检测失败：{exc}"
        run.metrics = {"error": str(exc)[:300]}
    run.finished_at = utcnow()
    db.flush()
    return run


def create_and_execute(
    db: Session,
    *,
    store_id: int | None,
    trigger: str,
    operator_email: str,
    params: dict | None = None,
    seed_key: str | None = None,
) -> Run:
    if seed_key:
        existing = db.scalar(select(Run).where(Run.seed_key == seed_key))
        if existing is not None:
            return existing
    if store_id and db.get(Store, store_id) is None:
        raise AppError("NOT_FOUND", 404, {"entity": "store", "id": store_id})
    run = Run(
        run_no=next_run_no(db),
        store_id=store_id,
        trigger=trigger,
        status="running",
        operator_email=operator_email,
        params=_normalize_params(params),
        seed_key=seed_key,
    )
    db.add(run)
    db.flush()
    return execute(db, run)


def list_runs(db: Session, *, status: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    stmt = select(Run)
    count_stmt = select(func.count()).select_from(Run)
    if status:
        stmt = stmt.where(Run.status == status)
        count_stmt = count_stmt.where(Run.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Run.id.desc()).limit(limit).offset(offset)).all()
    stores = {store.id: store.name for store in db.scalars(select(Store)).all()}
    return {
        "items": [serialize(row, stores.get(row.store_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_run(db: Session, run_id: int) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise AppError("NOT_FOUND", 404, {"entity": "run", "id": run_id})
    return run
