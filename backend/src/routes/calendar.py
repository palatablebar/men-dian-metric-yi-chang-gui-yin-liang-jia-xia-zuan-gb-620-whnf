from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import CALENDAR_WRITE_ROLES, READ_ROLES
from src.controllers import calendar_controller, generation_controller
from src.middlewares.rbac import require_roles
from src.schemas.calendar import CalendarRuleIn, CalendarRulePatch

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("")
def list_rules(
    store_id: int | None = None,
    day_type: str | None = None,
    active: bool | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return calendar_controller.list_rules(
        db, store_id=store_id, day_type=day_type, active=active, limit=limit, offset=offset
    )


@router.get("/version")
def version(db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))) -> dict:
    return calendar_controller.version(db)


@router.get("/revisions")
def revisions(
    limit: int = Query(20),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return calendar_controller.list_revisions(db, limit=limit)


@router.get("/store/{store_id}")
def store_calendar(
    store_id: int, db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))
) -> dict:
    return calendar_controller.store_calendar(db, store_id)


@router.post("", status_code=201)
def create_rule(
    payload: CalendarRuleIn,
    request: Request,
    recompute: bool = Query(True),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*CALENDAR_WRITE_ROLES)),
) -> dict:
    return calendar_controller.create(db, payload.model_dump(), principal, request, recompute=recompute)


@router.patch("/{rule_id}")
def update_rule(
    rule_id: int,
    payload: CalendarRulePatch,
    request: Request,
    recompute: bool = Query(True),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*CALENDAR_WRITE_ROLES)),
) -> dict:
    return calendar_controller.update(
        db, rule_id, payload.model_dump(exclude_unset=True), principal, request, recompute=recompute
    )


@router.delete("/{rule_id}")
def deactivate_rule(
    rule_id: int,
    request: Request,
    recompute: bool = Query(True),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*CALENDAR_WRITE_ROLES)),
) -> dict:
    return calendar_controller.deactivate(db, rule_id, principal, request, recompute=recompute)


@router.get("/jobs")
def list_jobs(
    limit: int = Query(20),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return generation_controller.list_jobs(db, limit=limit)


@router.post("/jobs/{job_id}/resume")
def resume_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*CALENDAR_WRITE_ROLES)),
) -> dict:
    return generation_controller.resume(db, job_id, principal, request)
