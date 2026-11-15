"""门店服务：CRUD + 序列化 + 区域聚合。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import STORE_STATUS_LABELS
from src.models.store import Store
from src.utils.errors import AppError, not_found
from src.utils.timeutil import iso_utc


def serialize(store: Store) -> dict:
    return {
        "id": store.id,
        "code": store.code,
        "name": store.name,
        "region": store.region,
        "city": store.city,
        "brand": store.brand,
        "room_count": store.room_count,
        "manager": store.manager,
        "status": store.status,
        "status_label": STORE_STATUS_LABELS.get(store.status, store.status),
        "note": store.note,
        "created_at": iso_utc(store.created_at),
    }


def list_stores(
    db: Session,
    *,
    q: str | None = None,
    region: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    stmt = select(Store)
    count_stmt = select(func.count()).select_from(Store)
    if q:
        like = f"%{q.strip()}%"
        condition = Store.name.ilike(like) | Store.code.ilike(like) | Store.city.ilike(like)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if region:
        stmt = stmt.where(Store.region == region)
        count_stmt = count_stmt.where(Store.region == region)
    if status:
        stmt = stmt.where(Store.status == status)
        count_stmt = count_stmt.where(Store.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Store.code).limit(limit).offset(offset)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def get_store(db: Session, store_id: int) -> Store:
    store = db.get(Store, store_id)
    if store is None:
        raise not_found("store", store_id)
    return store


def get_by_code(db: Session, code: str) -> Store | None:
    return db.scalar(select(Store).where(Store.code == code))


def regions(db: Session) -> list[dict]:
    rows = db.execute(select(Store.region, func.count()).group_by(Store.region)).all()
    return [{"region": region, "count": count} for region, count in sorted(rows)]


def create_store(db: Session, payload: dict) -> Store:
    if get_by_code(db, payload["code"]) is not None:
        raise AppError("CONFLICT", 409, {"code": payload["code"]})
    store = Store(
        code=payload["code"],
        name=payload["name"],
        region=payload["region"],
        city=payload["city"],
        brand=payload.get("brand") or "蓝湾精选",
        room_count=int(payload.get("room_count") or 200),
        manager=payload.get("manager") or "",
        status=payload.get("status") or "open",
        note=payload.get("note"),
    )
    db.add(store)
    db.flush()
    return store


def update_store(db: Session, store: Store, payload: dict) -> Store:
    for field in ("name", "region", "city", "brand", "room_count", "manager", "status", "note"):
        if field in payload and payload[field] is not None:
            setattr(store, field, payload[field])
    db.flush()
    return store
