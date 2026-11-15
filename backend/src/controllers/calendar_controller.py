"""运营日历控制器：规则维护 + 版本化失效重算。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, calendar_service, generation_service


def _record(db: Session, principal: dict, request: Request, action: str, rule, revision) -> None:
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action=action,
        entity="calendar_rule",
        entity_id=rule.id,
        detail={
            "store_id": rule.store_id,
            "day_type": rule.day_type,
            "start_date": rule.start_date.isoformat(),
            "end_date": rule.end_date.isoformat(),
            "calendar_version": revision.version,
        },
        ip=request.client.host if request.client else None,
    )


def _change_response(db: Session, rule, revision, impact: dict) -> dict:
    return {
        "rule": calendar_service.serialize_rule(rule),
        "revision": calendar_service.serialize_revision(revision),
        "calendar_version": revision.version,
        "impact": impact,
        "invalidated_drafts": len(impact.get("draft_report_ids") or []),
        "published_preserved": impact.get("published_report_ids") or [],
    }


def list_rules(db: Session, **filters) -> dict:
    return calendar_service.list_rules(db, **filters)


def store_calendar(db: Session, store_id: int) -> dict:
    return calendar_service.store_calendar(db, store_id)


def list_revisions(db: Session, limit: int = 20) -> dict:
    return calendar_service.list_revisions(db, limit=limit)


def create(db: Session, payload: dict, principal: dict, request: Request, recompute: bool = True) -> dict:
    rule, revision = calendar_service.create_rule(db, payload, principal["email"])
    impact = calendar_service.impacted_scope(db, [rule.store_id])
    invalidated = calendar_service.invalidate_scope(db, impact, revision.version)
    _record(db, principal, request, "calendar.create", rule, revision)
    job = None
    if recompute:
        job = generation_service.start(db, revision=revision, operator=principal["email"])
    db.commit()
    response = _change_response(db, rule, revision, impact)
    response["invalidated"] = invalidated
    response["job"] = generation_service.serialize(job) if job else None
    return response


def update(db: Session, rule_id: int, payload: dict, principal: dict, request: Request, recompute: bool = True) -> dict:
    rule, revision = calendar_service.update_rule(db, rule_id, payload, principal["email"])
    impact = calendar_service.impacted_scope(db, [rule.store_id])
    invalidated = calendar_service.invalidate_scope(db, impact, revision.version)
    _record(db, principal, request, "calendar.update", rule, revision)
    job = None
    if recompute:
        job = generation_service.start(db, revision=revision, operator=principal["email"])
    db.commit()
    response = _change_response(db, rule, revision, impact)
    response["invalidated"] = invalidated
    response["job"] = generation_service.serialize(job) if job else None
    return response


def deactivate(db: Session, rule_id: int, principal: dict, request: Request, recompute: bool = True) -> dict:
    rule, revision = calendar_service.deactivate_rule(db, rule_id, principal["email"])
    impact = calendar_service.impacted_scope(db, [rule.store_id])
    invalidated = calendar_service.invalidate_scope(db, impact, revision.version)
    _record(db, principal, request, "calendar.deactivate", rule, revision)
    job = None
    if recompute:
        job = generation_service.start(db, revision=revision, operator=principal["email"])
    db.commit()
    response = _change_response(db, rule, revision, impact)
    response["invalidated"] = invalidated
    response["job"] = generation_service.serialize(job) if job else None
    return response


def version(db: Session) -> dict:
    return calendar_service.version_info(db)
