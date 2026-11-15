"""异常服务：列表 / 详情 / 复核 / 序列化。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    DIRECTION_LABELS,
    METRIC_LABELS,
    REVIEW_STATUS_LABELS,
    SEVERITY_LABELS,
)
from src.models.anomaly import Anomaly
from src.models.attribution import Attribution
from src.models.store import Store
from src.utils.errors import AppError, not_found
from src.utils.timeutil import iso_utc, parse_date, utcnow


def serialize(anomaly: Anomaly, store: Store | None = None, attribution_id: int | None = None) -> dict:
    return {
        "id": anomaly.id,
        "run_id": anomaly.run_id,
        "store_id": anomaly.store_id,
        "store_code": store.code if store else None,
        "store_name": store.name if store else None,
        "region": store.region if store else None,
        "city": store.city if store else None,
        "metric_date": anomaly.metric_date.isoformat(),
        "metric_key": anomaly.metric_key,
        "metric_label": METRIC_LABELS.get(anomaly.metric_key, anomaly.metric_key),
        "observed": round(anomaly.observed, 2),
        "baseline": round(anomaly.baseline, 2),
        "mad": round(anomaly.mad, 2),
        "robust_z": round(anomaly.robust_z, 4),
        "direction": anomaly.direction,
        "direction_label": DIRECTION_LABELS.get(anomaly.direction, anomaly.direction),
        "severity": anomaly.severity,
        "severity_label": SEVERITY_LABELS.get(anomaly.severity, anomaly.severity),
        "impact_amount": round(anomaly.impact_amount, 2),
        "status": anomaly.status,
        "status_label": REVIEW_STATUS_LABELS.get(anomaly.status, anomaly.status),
        "reviewer": anomaly.reviewer,
        "review_note": anomaly.review_note,
        "reviewed_at": iso_utc(anomaly.reviewed_at),
        "attribution_id": attribution_id,
        "payload": anomaly.payload or {},
        "calendar_version": anomaly.calendar_version,
        "invalidated": anomaly.invalidated,
        "invalidated_reason": anomaly.invalidated_reason,
        "invalidated_by_version": anomaly.invalidated_by_version,
        "created_at": iso_utc(anomaly.created_at),
        "updated_at": iso_utc(anomaly.updated_at),
    }


def _attribution_map(db: Session) -> dict[int, int]:
    rows = db.execute(select(Attribution.anomaly_id, Attribution.id)).all()
    return {anomaly_id: attribution_id for anomaly_id, attribution_id in rows}


def list_anomalies(
    db: Session,
    *,
    store_id: int | None = None,
    region: str | None = None,
    metric_key: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    include_invalidated: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    stmt = select(Anomaly)
    count_stmt = select(func.count()).select_from(Anomaly)
    conditions = []
    if not include_invalidated:
        conditions.append(Anomaly.invalidated.is_(False))
    if store_id:
        conditions.append(Anomaly.store_id == store_id)
    if metric_key:
        conditions.append(Anomaly.metric_key == metric_key)
    if severity:
        conditions.append(Anomaly.severity == severity)
    if status:
        conditions.append(Anomaly.status == status)
    parsed_from = parse_date(date_from)
    parsed_to = parse_date(date_to)
    if parsed_from:
        conditions.append(Anomaly.metric_date >= parsed_from)
    if parsed_to:
        conditions.append(Anomaly.metric_date <= parsed_to)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if region or q:
        store_stmt = select(Store.id)
        if region:
            store_stmt = store_stmt.where(Store.region == region)
        if q:
            like = f"%{q.strip()}%"
            store_stmt = store_stmt.where(Store.name.ilike(like) | Store.code.ilike(like))
        store_ids = [row for row in db.scalars(store_stmt).all()]
        if not store_ids:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        stmt = stmt.where(Anomaly.store_id.in_(store_ids))
        count_stmt = count_stmt.where(Anomaly.store_id.in_(store_ids))
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(Anomaly.metric_date.desc(), func.abs(Anomaly.robust_z).desc()).limit(limit).offset(offset)
    ).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    attribution_ids = _attribution_map(db)
    return {
        "items": [
            serialize(row, stores.get(row.store_id), attribution_ids.get(row.id))
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_anomaly(db: Session, anomaly_id: int) -> Anomaly:
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise not_found("anomaly", anomaly_id)
    return anomaly


def get_with_context(db: Session, anomaly_id: int) -> dict:
    anomaly = get_anomaly(db, anomaly_id)
    store = db.get(Store, anomaly.store_id)
    attribution_ids = _attribution_map(db)
    return serialize(anomaly, store, attribution_ids.get(anomaly.id))


def review(db: Session, anomaly: Anomaly, *, status: str, note: str | None, reviewer: str) -> Anomaly:
    anomaly.status = status
    anomaly.review_note = note
    anomaly.reviewer = reviewer
    anomaly.reviewed_at = utcnow()
    anomaly.updated_at = utcnow()
    db.flush()
    return anomaly


def count_by(db: Session, column) -> list[tuple[str, int]]:
    return db.execute(select(column, func.count()).group_by(column)).all()


def ensure_anomaly(db: Session, payload: dict) -> tuple[Anomaly, bool]:
    """自然键 (store_id, metric_date, metric_key) 幂等 upsert；不覆盖复核状态、不重复入库。

    已复核（confirmed / dismissed）的异常只补充检测字段与样本引用，状态与结论原样保留；
    这也是「同版本重跑不退还复核」的保证。
    """
    existing = db.scalar(
        select(Anomaly).where(
            Anomaly.store_id == payload["store_id"],
            Anomaly.metric_date == payload["metric_date"],
            Anomaly.metric_key == payload["metric_key"],
        )
    )
    if existing is not None:
        existing.run_id = payload.get("run_id") or existing.run_id
        existing.observed = payload["observed"]
        existing.baseline = payload["baseline"]
        existing.mad = payload["mad"]
        existing.robust_z = payload["robust_z"]
        existing.severity = payload["severity"]
        existing.impact_amount = payload["impact_amount"]
        existing.payload = payload["payload"]
        existing.calendar_version = int(payload.get("calendar_version") or 0)
        db.flush()
        return existing, False
    anomaly = Anomaly(**payload)
    db.add(anomaly)
    db.flush()
    return anomaly, True


def mark_reviewed(db: Session, anomaly: Anomaly, reviewer: str, note: str) -> None:
    if anomaly.status != "pending":
        return
    if not reviewer:
        raise AppError("VALIDATION", 422, {"field": "reviewer"})
    anomaly.status = "confirmed" if anomaly.severity in ("high", "medium") else "dismissed"
    anomaly.reviewer = reviewer
    anomaly.review_note = note
    anomaly.reviewed_at = utcnow()
    db.flush()
