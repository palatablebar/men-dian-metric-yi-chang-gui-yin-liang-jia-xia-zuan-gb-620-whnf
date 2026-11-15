from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import READ_ROLES, STORE_WRITE_ROLES
from src.controllers import store_controller
from src.middlewares.rbac import require_roles
from src.schemas.store import StoreIn, StorePatch
from src.services import metric_service, store_service
from src.utils.pagination import page_params

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("")
def list_stores(
    q: str | None = None,
    region: str | None = None,
    status: str | None = None,
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return store_controller.list_stores(db, q=q, region=region, status=status, limit=page.limit, offset=page.offset)


@router.get("/regions")
def list_regions(db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))) -> dict:
    return {"items": store_service.regions(db)}


@router.get("/{store_id}")
def get_store(store_id: int, db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))) -> dict:
    return store_controller.get_store(db, store_id)


@router.get("/{store_id}/series")
def store_series(
    store_id: int,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    from src.utils.timeutil import parse_date

    bounds = metric_service.date_bounds(db)
    start_date = parse_date(start) or bounds[0]
    end_date = parse_date(end) or bounds[1]
    series = metric_service.store_series(db, store_id, start_date, end_date)
    return {
        "store_id": store_id,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "points": series,
        "summary": {
            "days": len(series),
            "revenue": round(sum(item["revenue"] for item in series), 2),
            "adr": round(sum(item["revenue"] for item in series) / max(1, sum(item["rooms_sold"] for item in series)), 2),
            "occupancy": round(
                sum(item["rooms_sold"] for item in series)
                / max(1, sum(item["rooms_available"] for item in series)),
                4,
            ),
        },
    }


@router.post("", status_code=201)
def create_store(
    payload: StoreIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*STORE_WRITE_ROLES)),
) -> dict:
    return store_controller.create_store(db, payload.model_dump(), principal, request)


@router.patch("/{store_id}")
def update_store(
    store_id: int,
    payload: StorePatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*STORE_WRITE_ROLES)),
) -> dict:
    return store_controller.update_store(db, store_id, payload.model_dump(exclude_unset=True), principal, request)
