"""指标服务：明细查询 + 门店日序列聚合（异常检测与页面共用同一口径）。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import CHANNEL_LABELS
from src.models.metric import MetricPoint
from src.models.store import Store
from src.utils.errors import not_found
from src.utils.timeutil import iso_date
from src.utils.pagination import page_params


def median(values: list[float]) -> float:
    ordered = sorted(values)
    size = len(ordered)
    if size == 0:
        return 0.0
    if size % 2:
        return ordered[size // 2]
    return (ordered[size // 2 - 1] + ordered[size // 2]) / 2


def serialize_point(point: MetricPoint, store: Store | None = None) -> dict:
    return {
        "id": point.id,
        "store_id": point.store_id,
        "store_code": store.code if store else None,
        "store_name": store.name if store else None,
        "stat_date": iso_date(point.stat_date),
        "channel": point.channel,
        "channel_label": CHANNEL_LABELS.get(point.channel, point.channel),
        "rooms_available": point.rooms_available,
        "rooms_sold": point.rooms_sold,
        "occupancy": round(point.occupancy, 4),
        "adr": round(point.adr, 2),
        "revenue": round(point.revenue, 2),
        "is_weekend": point.is_weekend,
        "room_type_mix": point.room_type_mix or {},
    }


def list_points(
    db: Session,
    *,
    store_id: int | None = None,
    channel: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(MetricPoint)
    count_stmt = select(func.count()).select_from(MetricPoint)
    conditions = []
    if store_id:
        conditions.append(MetricPoint.store_id == store_id)
    if channel:
        conditions.append(MetricPoint.channel == channel)
    if date_from:
        conditions.append(MetricPoint.stat_date >= date_from)
    if date_to:
        conditions.append(MetricPoint.stat_date <= date_to)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    page = page_params(limit, offset)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(MetricPoint.stat_date.desc(), MetricPoint.channel).limit(page.limit).offset(page.offset)
    ).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    return {
        "items": [serialize_point(row, stores.get(row.store_id)) for row in rows],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


def store_series(db: Session, store_id: int, start: date, end: date) -> list[dict]:
    """门店日序列：营收/售量按日汇总，ADR = 营收/售量、OCC = 售量/可售房量。"""
    if db.get(Store, store_id) is None:
        raise not_found("store", store_id)
    rows = db.execute(
        select(
            MetricPoint.stat_date,
            func.sum(MetricPoint.revenue),
            func.sum(MetricPoint.rooms_sold),
            func.max(MetricPoint.rooms_available),
            func.max(MetricPoint.is_weekend),
        )
        .where(
            MetricPoint.store_id == store_id,
            MetricPoint.stat_date >= start,
            MetricPoint.stat_date <= end,
        )
        .group_by(MetricPoint.stat_date)
        .order_by(MetricPoint.stat_date)
    ).all()
    series: list[dict] = []
    for stat_date, revenue, sold, rooms, weekend in rows:
        revenue = float(revenue or 0.0)
        sold = int(sold or 0)
        rooms = int(rooms or 0)
        series.append(
            {
                "date": stat_date.isoformat(),
                "revenue": round(revenue, 2),
                "rooms_sold": sold,
                "rooms_available": rooms,
                "adr": round(revenue / sold, 4) if sold else 0.0,
                "occupancy": round(sold / rooms, 6) if rooms else 0.0,
                "is_weekend": bool(weekend),
            }
        )
    return series


def channel_split(db: Session, store_id: int, stat_date: date) -> dict[str, float]:
    rows = db.execute(
        select(MetricPoint.channel, func.sum(MetricPoint.revenue))
        .where(MetricPoint.store_id == store_id, MetricPoint.stat_date == stat_date)
        .group_by(MetricPoint.channel)
    ).all()
    return {channel: float(revenue or 0.0) for channel, revenue in rows}


def channel_window(db: Session, store_id: int, start: date, end: date) -> dict[str, list[float]]:
    rows = db.execute(
        select(MetricPoint.channel, MetricPoint.stat_date, func.sum(MetricPoint.revenue))
        .where(
            MetricPoint.store_id == store_id,
            MetricPoint.stat_date >= start,
            MetricPoint.stat_date <= end,
        )
        .group_by(MetricPoint.channel, MetricPoint.stat_date)
    ).all()
    bucket: dict[str, list[float]] = {}
    for channel, _, revenue in rows:
        bucket.setdefault(channel, []).append(float(revenue or 0.0))
    return bucket


def series_points(db: Session, start: date, end: date, store_id: int | None = None) -> dict[int, list[dict]]:
    """批量取门店日序列（检测运行用，一次聚合查询）。"""
    stmt = (
        select(
            MetricPoint.store_id,
            MetricPoint.stat_date,
            func.sum(MetricPoint.revenue),
            func.sum(MetricPoint.rooms_sold),
            func.max(MetricPoint.rooms_available),
            func.max(MetricPoint.is_weekend),
        )
        .where(MetricPoint.stat_date >= start, MetricPoint.stat_date <= end)
        .group_by(MetricPoint.store_id, MetricPoint.stat_date)
        .order_by(MetricPoint.store_id, MetricPoint.stat_date)
    )
    if store_id:
        stmt = stmt.where(MetricPoint.store_id == store_id)
    rows = db.execute(stmt).all()
    grouped: dict[int, list[dict]] = {}
    for store_key, stat_date, revenue, sold, rooms, weekend in rows:
        revenue = float(revenue or 0.0)
        sold = int(sold or 0)
        rooms = int(rooms or 0)
        grouped.setdefault(store_key, []).append(
            {
                "date": stat_date.isoformat(),
                "revenue": round(revenue, 2),
                "rooms_sold": sold,
                "rooms_available": rooms,
                "adr": round(revenue / sold, 6) if sold else 0.0,
                "occupancy": round(sold / rooms, 6) if rooms else 0.0,
                "is_weekend": bool(weekend),
            }
        )
    return grouped


def date_bounds(db: Session) -> tuple[date, date]:
    row = db.execute(select(func.min(MetricPoint.stat_date), func.max(MetricPoint.stat_date))).one()
    if row is None or row[0] is None:
        today = date.today()
        return today - timedelta(days=1), today
    return row[0], row[1]
