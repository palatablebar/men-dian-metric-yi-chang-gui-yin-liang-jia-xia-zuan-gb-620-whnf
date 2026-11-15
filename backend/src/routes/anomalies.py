from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import READ_ROLES, REVIEW_ROLES
from src.controllers import anomaly_controller
from src.middlewares.rbac import require_roles
from src.schemas.anomaly import ReviewIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("")
def list_anomalies(
    store_id: int | None = None,
    region: str | None = None,
    metric_key: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return anomaly_controller.list_anomalies(
        db,
        store_id=store_id,
        region=region,
        metric_key=metric_key,
        severity=severity,
        status=status,
        date_from=date_from,
        date_to=date_to,
        q=q,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{anomaly_id}")
def get_anomaly(
    anomaly_id: int, db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))
) -> dict:
    return anomaly_controller.get_anomaly(db, anomaly_id)


@router.patch("/{anomaly_id}/review")
def review(
    anomaly_id: int,
    payload: ReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*REVIEW_ROLES)),
) -> dict:
    return anomaly_controller.review(db, anomaly_id, payload.model_dump(), principal, request)
