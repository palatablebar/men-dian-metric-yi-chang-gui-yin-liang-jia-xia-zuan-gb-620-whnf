"""失效重算任务控制器：查看 / 续跑。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, generation_service


def list_jobs(db: Session, **filters) -> dict:
    return generation_service.list_jobs(db, **filters)


def get_job(db: Session, job_id: int) -> dict:
    return generation_service.serialize(generation_service.get_job(db, job_id))


def resume(db: Session, job_id: int, principal: dict, request: Request) -> dict:
    job = generation_service.resume(db, job_id, operator=principal["email"])
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="calendar.recompute.resume",
        entity="generation_job",
        entity_id=job.id,
        detail={"job_no": job.job_no, "status": job.status, "recovered_from": job.recovered_from},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return generation_service.serialize(job)
