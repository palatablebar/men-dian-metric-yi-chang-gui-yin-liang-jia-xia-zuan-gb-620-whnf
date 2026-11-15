"""门店控制器：写操作记领域审计。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, store_service


def list_stores(db: Session, **filters) -> dict:
    return store_service.list_stores(db, **filters)


def get_store(db: Session, store_id: int) -> dict:
    return store_service.serialize(store_service.get_store(db, store_id))


def create_store(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    store = store_service.create_store(db, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="store.create",
        entity="store",
        entity_id=store.id,
        detail={"code": store.code, "region": store.region},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return store_service.serialize(store)


def update_store(db: Session, store_id: int, payload: dict, principal: dict, request: Request) -> dict:
    store = store_service.get_store(db, store_id)
    store_service.update_store(db, store, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="store.update",
        entity="store",
        entity_id=store.id,
        detail={"fields": list(payload.keys())},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return store_service.serialize(store)
