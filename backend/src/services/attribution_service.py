"""归因服务：量价分解（算法 B）+ 门店/渠道/房型三维贡献 + 结论文本。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import CHANNEL_LABELS, CHANNEL_ORDER, METRIC_LABELS
from src.models.anomaly import Anomaly
from src.models.attribution import Attribution
from src.models.metric import MetricPoint
from src.models.store import Store
from src.services import decompose, metric_service
from src.utils.errors import not_found
from src.utils.timeutil import iso_utc, parse_date


def serialize(attribution: Attribution, anomaly: Anomaly | None = None, store: Store | None = None) -> dict:
    return {
        "id": attribution.id,
        "anomaly_id": attribution.anomaly_id,
        "store_id": attribution.store_id,
        "store_code": store.code if store else None,
        "store_name": store.name if store else None,
        "metric_date": anomaly.metric_date.isoformat() if anomaly else None,
        "metric_key": anomaly.metric_key if anomaly else None,
        "metric_label": METRIC_LABELS.get(anomaly.metric_key, anomaly.metric_key) if anomaly else None,
        "method": attribution.method,
        "status": attribution.status,
        "base_rev": round(attribution.base_rev, 2),
        "cur_rev": round(attribution.cur_rev, 2),
        "total_delta": round(attribution.total_delta, 2),
        "parts": {
            "adr": round(attribution.adr_part, 2),
            "occ": round(attribution.occ_part, 2),
            "rooms": round(attribution.rooms_part, 2),
        },
        "shares": {
            "adr": None if attribution.adr_share is None else round(attribution.adr_share, 6),
            "occ": None if attribution.occ_share is None else round(attribution.occ_share, 6),
            "rooms": None if attribution.rooms_share is None else round(attribution.rooms_share, 6),
        },
        "residual": round(attribution.residual, 4),
        "drivers": attribution.drivers or {},
        "dimensions": attribution.dimensions or {},
        "narrative": attribution.narrative,
        "created_at": iso_utc(attribution.created_at),
    }


def _window_range(anomaly: Anomaly) -> tuple[date, date]:
    payload = anomaly.payload or {}
    start = parse_date(payload.get("window_start")) or (anomaly.metric_date - timedelta(days=56))
    end = parse_date(payload.get("window_end")) or (anomaly.metric_date - timedelta(days=1))
    return start, end


def _channel_rows(db: Session, anomaly: Anomaly) -> list[dict]:
    start, end = _window_range(anomaly)
    window = metric_service.channel_window(db, anomaly.store_id, start, end)
    current = metric_service.channel_split(db, anomaly.store_id, anomaly.metric_date)
    groups = []
    for channel in CHANNEL_ORDER:
        base = metric_service.median(window.get(channel, [])) if window.get(channel) else 0.0
        groups.append({"key": CHANNEL_LABELS.get(channel, channel), "value": current.get(channel, 0.0), "base": base})
    return groups


def _region_store_rows(db: Session, anomaly: Anomaly) -> list[dict]:
    store = db.get(Store, anomaly.store_id)
    if store is None:
        return []
    peers = db.scalars(select(Store).where(Store.region == store.region)).all()
    peer_ids = [peer.id for peer in peers]
    start = anomaly.metric_date - timedelta(days=56)
    rows = db.execute(
        select(MetricPoint.store_id, MetricPoint.stat_date, func.sum(MetricPoint.revenue))
        .where(
            MetricPoint.store_id.in_(peer_ids),
            MetricPoint.stat_date >= start,
            MetricPoint.stat_date <= anomaly.metric_date,
        )
        .group_by(MetricPoint.store_id, MetricPoint.stat_date)
    ).all()
    bucket: dict[int, dict[date, float]] = {}
    for store_id, stat_date, revenue in rows:
        bucket.setdefault(store_id, {})[stat_date] = float(revenue or 0.0)
    groups = []
    for peer in peers:
        daily = bucket.get(peer.id, {})
        current = daily.get(anomaly.metric_date)
        if current is None:
            continue
        reference = [
            value
            for day, value in daily.items()
            if day != anomaly.metric_date and day.weekday() < 5 and anomaly.metric_date.weekday() < 5
        ]
        base = metric_service.median(reference) if reference else current
        groups.append({"key": f"{peer.name}（{peer.code}）", "value": current, "base": base})
    return groups


def _room_type_rows(store: Store, total: float, delta: float) -> list[dict]:
    mix = {"大床房": 0.52, "双床房": 0.36, "套房": 0.12}
    groups = []
    for name, share in mix.items():
        groups.append({"key": name, "value": round(total * share, 2), "base": round((total - delta) * share, 2)})
    return groups


def build(db: Session, anomaly: Anomaly, store: Store | None = None) -> Attribution:
    existing = db.scalar(select(Attribution).where(Attribution.anomaly_id == anomaly.id))
    if existing is not None:
        return existing
    store = store or db.get(Store, anomaly.store_id)
    payload = anomaly.payload or {}
    base = payload.get("baseline_triple") or {}
    current = payload.get("current_triple") or {}
    triple_base = {
        "adr": float(base.get("adr") or anomaly.baseline),
        "occ": float(base.get("occ") or 0.0),
        "rooms": float(base.get("rooms") or 0.0),
        "revenue": float(anomaly.baseline),
    }
    triple_cur = {
        "adr": float(current.get("adr") or anomaly.observed),
        "occ": float(current.get("occ") or 0.0),
        "rooms": float(current.get("rooms") or 0.0),
        "revenue": float(anomaly.observed),
    }
    result = decompose.decompose(triple_base, triple_cur)

    channel_rows = _channel_rows(db, anomaly)
    channel_rank = decompose.rank_contributions(channel_rows, result["total_delta"])
    store_rank = decompose.rank_contributions(_region_store_rows(db, anomaly), result["total_delta"])
    room_rows = _room_type_rows(store, triple_cur["revenue"], result["total_delta"])
    room_rank = decompose.rank_contributions(room_rows, result["total_delta"])

    dimensions = {
        "channel": {"label": "渠道", "rows": channel_rank["rows"], "top_negative": channel_rank["top_negative"], "top_positive": channel_rank["top_positive"]},
        "store": {"label": "门店（同区域）", "rows": store_rank["rows"], "top_negative": store_rank["top_negative"], "top_positive": store_rank["top_positive"]},
        "room_type": {"label": "房型（按房型结构分摊）", "rows": room_rank["rows"], "top_negative": room_rank["top_negative"], "top_positive": room_rank["top_positive"]},
    }
    narrative = decompose.narrative(
        result, channel_rank["rows"], store.name if store else anomaly.payload.get("store_code", ""), anomaly.metric_date.isoformat()
    )
    shares = result["shares"]
    attribution = Attribution(
        anomaly_id=anomaly.id,
        store_id=anomaly.store_id,
        method=result["method"],
        status=result["status"],
        base_rev=triple_base["revenue"],
        cur_rev=triple_cur["revenue"],
        total_delta=result["total_delta"],
        adr_part=result["parts"]["adr"] or 0.0,
        occ_part=result["parts"]["occ"] or 0.0,
        rooms_part=result["parts"]["rooms"] or 0.0,
        adr_share=shares["adr"],
        occ_share=shares["occ"],
        rooms_share=shares["rooms"],
        residual=result["residual"] or 0.0,
        drivers={
            "base": result["base"],
            "current": result["current"],
            "reason": result["reason"],
            "log_mean_weight": result.get("log_mean_weight"),
        },
        dimensions=dimensions,
        narrative=narrative,
    )
    db.add(attribution)
    db.flush()
    return attribution


def get_by_anomaly(db: Session, anomaly_id: int) -> dict:
    attribution = db.scalar(select(Attribution).where(Attribution.anomaly_id == anomaly_id))
    if attribution is None:
        anomaly = db.get(Anomaly, anomaly_id)
        if anomaly is None:
            raise not_found("anomaly", anomaly_id)
        attribution = build(db, anomaly)
        db.commit()
    anomaly = db.get(Anomaly, attribution.anomaly_id)
    store = db.get(Store, attribution.store_id)
    return serialize(attribution, anomaly, store)


def list_attributions(db: Session, *, limit: int = 20, offset: int = 0) -> dict:
    total = db.scalar(select(func.count()).select_from(Attribution)) or 0
    rows = db.scalars(select(Attribution).order_by(Attribution.id.desc()).limit(limit).offset(offset)).all()
    anomalies = {row.id: row for row in db.scalars(select(Anomaly)).all()}
    stores = {row.id: row for row in db.scalars(select(Store)).all()}
    return {
        "items": [serialize(row, anomalies.get(row.anomaly_id), stores.get(row.store_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
