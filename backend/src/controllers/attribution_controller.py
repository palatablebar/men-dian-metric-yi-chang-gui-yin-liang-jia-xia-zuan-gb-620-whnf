"""归因控制器：按异常取归因（不存在则按当前口径即时生成并留痕）。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import attribution_service, audit_service


def get_for_anomaly(db: Session, anomaly_id: int, principal: dict, request: Request) -> dict:
    result = attribution_service.get_by_anomaly(db, anomaly_id)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="attribution.build",
        entity="attribution",
        entity_id=result.get("id"),
        detail={"anomaly_id": anomaly_id, "method": result.get("method")},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return result


def list_attributions(db: Session, **filters) -> dict:
    return attribution_service.list_attributions(db, **filters)
