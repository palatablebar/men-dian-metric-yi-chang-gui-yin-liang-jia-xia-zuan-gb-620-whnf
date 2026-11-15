"""报告控制器：生成 / 发布 / 详情。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, report_service


def list_reports(db: Session, **filters) -> dict:
    return report_service.list_reports(db, **filters)


def get_report(db: Session, report_id: int) -> dict:
    return report_service.serialize(report_service.get_report(db, report_id))


def generate(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    report = report_service.generate(db, payload, principal["email"])
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="report.generate",
        entity="report",
        entity_id=report.id,
        detail={"report_no": report.report_no, "anomalies": report.anomaly_count, "impact": report.impact_total},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return report_service.serialize(report)


def publish(db: Session, report_id: int, payload: dict, principal: dict, request: Request) -> dict:
    report = report_service.get_report(db, report_id)
    report_service.publish(db, report, payload["status"], payload.get("note"))
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="report.publish",
        entity="report",
        entity_id=report.id,
        detail={"status": report.status},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return report_service.serialize(report)
