from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from fastapi import Response

from src.config.database import get_db
from src.constants.roles import EXPORT_ROLES
from src.controllers import export_controller
from src.middlewares.rbac import require_roles
from src.services import audit_service, export_service
from src.utils.csv_export import csv_response_headers

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/anomalies.csv")
def anomalies_csv(
    request: Request,
    store_id: int | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*EXPORT_ROLES)),
):
    return export_controller.anomalies_csv(db, store_id, severity, principal, request)


@router.get("/attributions.csv")
def attributions_csv(
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*EXPORT_ROLES)),
):
    return export_controller.attributions_csv(db, principal, request)


@router.get("/channels.csv")
def channels_csv(
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*EXPORT_ROLES)),
):
    content = export_service.channels_csv(db)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.attributions",
        entity="attribution",
        detail={"bytes": len(content), "kind": "channels"},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=csv_response_headers("channels.csv"))


@router.get("/reports/{report_id}.csv")
def report_csv(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*EXPORT_ROLES)),
):
    return export_controller.report_csv(db, report_id, principal, request)
