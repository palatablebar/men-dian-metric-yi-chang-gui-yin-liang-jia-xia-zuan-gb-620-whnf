from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import READ_ROLES
from src.middlewares.rbac import require_roles
from src.services import metric_service
from src.utils.timeutil import parse_date

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
def list_points(
    store_id: int | None = None,
    channel: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return metric_service.list_points(
        db,
        store_id=store_id,
        channel=channel,
        date_from=parse_date(date_from),
        date_to=parse_date(date_to),
        limit=limit,
        offset=offset,
    )


@router.get("/channel-split")
def channel_split(
    store_id: int,
    stat_date: str,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    parsed = parse_date(stat_date)
    return {"store_id": store_id, "stat_date": stat_date, "items": metric_service.channel_split(db, store_id, parsed)}
