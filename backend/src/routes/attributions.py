from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import READ_ROLES
from src.controllers import attribution_controller
from src.middlewares.rbac import require_roles

router = APIRouter(prefix="/attributions", tags=["attributions"])


@router.get("")
def list_attributions(
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return attribution_controller.list_attributions(db, limit=limit, offset=offset)


@router.get("/anomaly/{anomaly_id}")
def get_attribution(
    anomaly_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return attribution_controller.get_for_anomaly(db, anomaly_id, principal, request)
