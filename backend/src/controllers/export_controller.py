"""导出控制器：CSV 响应 + 审计。"""
from __future__ import annotations

from fastapi import Request, Response
from sqlalchemy.orm import Session

from src.services import audit_service, export_service, report_service
from src.utils.csv_export import csv_response_headers


def anomalies_csv(db: Session, store_id: int | None, severity: str | None, principal: dict, request: Request) -> Response:
    content = export_service.anomalies_csv(db, store_id, severity)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.anomalies",
        entity="anomaly",
        entity_id=store_id,
        detail={"bytes": len(content)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=csv_response_headers("anomalies.csv"))


def attributions_csv(db: Session, principal: dict, request: Request) -> Response:
    content = export_service.attributions_csv(db)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.attributions",
        entity="attribution",
        detail={"bytes": len(content)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=csv_response_headers("attributions.csv"))


def report_csv(db: Session, report_id: int, principal: dict, request: Request) -> Response:
    report = report_service.get_report(db, report_id)
    content = export_service.report_csv(db, report)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.report",
        entity="report",
        entity_id=report.id,
        detail={"bytes": len(content)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=csv_response_headers(f"{report.report_no}.csv"),
    )
