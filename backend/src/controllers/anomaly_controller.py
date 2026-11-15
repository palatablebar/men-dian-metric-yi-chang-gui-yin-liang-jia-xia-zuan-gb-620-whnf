"""异常控制器：列表 / 详情 / 复核（写结论）。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import anomaly_service, audit_service


def list_anomalies(db: Session, **filters) -> dict:
    return anomaly_service.list_anomalies(db, **filters)


def get_anomaly(db: Session, anomaly_id: int) -> dict:
    return anomaly_service.get_with_context(db, anomaly_id)


def review(db: Session, anomaly_id: int, payload: dict, principal: dict, request: Request) -> dict:
    anomaly = anomaly_service.get_anomaly(db, anomaly_id)
    anomaly_service.review(
        db,
        anomaly,
        status=payload["status"],
        note=payload.get("note"),
        reviewer=principal["email"],
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="anomaly.review",
        entity="anomaly",
        entity_id=anomaly.id,
        detail={"status": anomaly.status, "severity": anomaly.severity, "impact": anomaly.impact_amount},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return anomaly_service.get_with_context(db, anomaly.id)
