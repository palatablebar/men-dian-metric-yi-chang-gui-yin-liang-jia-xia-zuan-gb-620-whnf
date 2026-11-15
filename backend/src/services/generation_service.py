"""生成任务服务：日历变更后的失效重算（异常重算 + 草稿报告重生成），带中断恢复与幂等。

三阶段（每阶段独立提交，进程中断后可续跑）：
1. `staged`：先把**完整旧版快照**（受影响门店的全部异常字段 + 草稿报告快照）写进 `job.staging["baseline"]`；
2. `applying`：按当前日历逐门店重算异常、逐份重算草稿报告，每次提交都更新 checkpoint；
3. `committed`：汇总结果、清理失效标记。

中断恢复（`resume`）：
- 只要上次没跑完（`failed` / 仍停在 `applying`），就**先用 baseline 把受影响对象恢复为完整旧版**
  （删除半途新增的异常与归因、还原被改写字段与草稿快照），再从第 2 阶段续跑；
- 同一日历版本重复执行：已有成功任务直接复用结果（`idempotent_hit=True`）；
  重跑本身也是幂等的：异常按自然键 upsert、归因按样本指纹复用，
  不会新增重复结果，也不会让已复核（confirmed/dismissed）的异常退回待处理。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.anomaly import Anomaly
from src.models.attribution import Attribution
from src.models.calendar import CalendarRevision
from src.models.generation import GenerationJob
from src.models.report import Report
from src.models.store import Store
from src.services import anomaly_service, attribution_service, calendar_service, detection, metric_service, report_service
from src.utils.errors import AppError, not_found
from src.utils.timeutil import local_now, utcnow

ANOMALY_FIELDS = (
    "run_id", "observed", "baseline", "mad", "robust_z", "direction", "severity", "impact_amount",
    "status", "reviewer", "review_note", "reviewed_at", "payload", "calendar_version",
    "invalidated", "invalidated_reason", "invalidated_by_version", "updated_at",
)

DATETIME_FIELDS = {"reviewed_at", "updated_at"}


def next_job_no(db: Session, kind: str) -> str:
    prefix = f"GJ{local_now():%Y%m%d}"
    count = db.scalar(select(func.count()).select_from(GenerationJob).where(GenerationJob.job_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:04d}-{kind}"


def serialize(job: GenerationJob) -> dict:
    summary = ((job.staging or {}).get("result") or {}).get("summary")
    return {
        "id": job.id,
        "job_no": job.job_no,
        "kind": job.kind,
        "calendar_version": job.calendar_version,
        "status": job.status,
        "stage": job.stage,
        "summary": summary,
        "checkpoint": (job.staging or {}).get("checkpoint"),
        "recoverable": job.status != "success",
        "idempotent_hit": job.idempotent_hit,
        "recovered_from": job.recovered_from,
        "log_text": job.log_text,
        "created_at": _stamp(job.created_at),
        "updated_at": _stamp(job.updated_at),
    }


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") + "Z" if value else None


def _anomaly_snapshot(anomaly: Anomaly) -> dict:
    snapshot = {}
    for field in ANOMALY_FIELDS:
        value = getattr(anomaly, field)
        snapshot[field] = value.isoformat() if isinstance(value, datetime) else value
    return snapshot


def _report_snapshot(report: Report) -> dict:
    return {
        "snapshot": report.snapshot or {},
        "anomaly_count": report.anomaly_count,
        "impact_total": report.impact_total,
        "calendar_version": report.calendar_version,
        "invalidated": report.invalidated,
        "invalidated_reason": report.invalidated_reason,
        "invalidated_by_version": report.invalidated_by_version,
        "generated_by": report.generated_by,
    }


def _capture_baseline(db: Session, store_ids: list[int], draft_ids: list[int]) -> dict:
    anomalies = (
        db.scalars(select(Anomaly).where(Anomaly.store_id.in_(store_ids)).order_by(Anomaly.id)).all()
        if store_ids
        else []
    )
    drafts = db.scalars(select(Report).where(Report.id.in_(draft_ids)).order_by(Report.id)).all() if draft_ids else []
    return {
        "state": "staged",
        "store_ids": store_ids,
        "anomalies": {str(row.id): _anomaly_snapshot(row) for row in anomalies},
        "drafts": {str(row.id): _report_snapshot(row) for row in drafts},
        "draft_ids": [row.id for row in drafts],
        "captured_at": utcnow().isoformat(timespec="seconds") + "Z",
        "calendar_version": calendar_service.current_version(db),
    }


def _restore_anomaly(anomaly: Anomaly, snapshot: dict) -> None:
    for field in ANOMALY_FIELDS:
        raw = snapshot.get(field)
        if field in DATETIME_FIELDS:
            setattr(anomaly, field, datetime.fromisoformat(raw) if raw else None)
        else:
            setattr(anomaly, field, raw)


def restore_baseline(db: Session, baseline: dict) -> dict:
    """恢复完整旧版：删除半途新增的异常/归因，还原被改写的异常字段与草稿快照。"""
    store_ids = [int(item) for item in (baseline.get("store_ids") or [])]
    snapshots = {int(key): value for key, value in (baseline.get("anomalies") or {}).items()}
    removed = 0
    restored = 0
    rows = db.scalars(select(Anomaly).where(Anomaly.store_id.in_(store_ids))).all() if store_ids else []
    for anomaly in rows:
        if anomaly.id in snapshots:
            _restore_anomaly(anomaly, snapshots[anomaly.id])
            restored += 1
            continue
        # 任务开始后才出现（半途新增）→ 删除并连带删除归因
        for attribution in db.scalars(select(Attribution).where(Attribution.anomaly_id == anomaly.id)).all():
            db.delete(attribution)
        db.delete(anomaly)
        removed += 1
    draft_snapshots = {int(key): value for key, value in (baseline.get("drafts") or {}).items()}
    drafts_restored = 0
    for report in db.scalars(select(Report).where(Report.id.in_(list(draft_snapshots.keys())))).all() if draft_snapshots else []:
        payload = draft_snapshots[report.id]
        for field, value in payload.items():
            setattr(report, field, value)
        drafts_restored += 1
    db.flush()
    return {"anomalies_restored": restored, "anomalies_removed": removed, "drafts_restored": drafts_restored}


def _recompute_store(db: Session, store: Store, series: list[dict], version: int) -> dict:
    result = detection.detect_series(series, "rev", window=28, threshold=3.5, persist_z=1.5, stratify=True)
    created = updated = review_kept = 0
    hit_keys: set[tuple[int, str, str]] = set()
    for hit in result["hits"]:
        hit_keys.add((store.id, hit["date"], "rev"))
        sample_key = hit["sample_key"]
        payload = {
            "store_id": store.id,
            "metric_date": date.fromisoformat(hit["date"]),
            "metric_key": "rev",
            "observed": hit["observed"],
            "baseline": hit["baseline"],
            "mad": hit["mad"],
            "robust_z": hit["robust_z"],
            "direction": hit["direction"],
            "severity": hit["severity"],
            "impact_amount": hit["impact_amount"],
            "run_id": None,
            "status": "pending",
            "payload": {
                "window_start": hit["window_start"],
                "window_end": hit["window_end"],
                "window_samples": hit["window_samples"],
                "window_dates": hit["window_dates"],
                "excluded_special_days": hit["excluded_special_days"],
                "mad_basis": hit["mad_basis"],
                "baseline_triple": hit["baseline_triple"],
                "current_triple": hit["current_triple"],
                "params": result["params"],
                "calendar_version": version,
                "sample_key": sample_key,
                "special_day": hit.get("special_day", False),
            },
            "calendar_version": version,
        }
        anomaly, is_new = anomaly_service.ensure_anomaly(db, payload)
        created += 1 if is_new else 0
        updated += 0 if is_new else 1
        if not is_new and anomaly.status != "pending":
            review_kept += 1
        anomaly.invalidated = False
        anomaly.invalidated_reason = None
        anomaly.invalidated_by_version = None
        attribution_service.build(db, anomaly, store)
    # 重算后不再命中的旧异常：标记失效（不删除，保留审计痕迹；已复核不动）
    stale = 0
    for anomaly in db.scalars(
        select(Anomaly).where(Anomaly.store_id == store.id, Anomaly.metric_key == "rev")
    ).all():
        if anomaly.status != "pending":
            continue
        if (anomaly.store_id, anomaly.metric_date.isoformat(), anomaly.metric_key) in hit_keys:
            continue
        if anomaly.invalidated:
            continue
        anomaly.invalidated = True
        anomaly.invalidated_reason = "not_in_recompute"
        anomaly.invalidated_by_version = version
        stale += 1
    db.flush()
    return {"created": created, "updated": updated, "review_kept": review_kept, "stale": stale, "hits": len(hit_keys)}


def _apply(db: Session, job: GenerationJob, *, operator: str, fail_at_store: int | None) -> dict:
    scope = job.payload or {}
    store_ids = [int(item) for item in (scope.get("store_ids") or [])]
    if fail_at_store is not None:
        store_ids = store_ids[: max(0, fail_at_store)]
    if not store_ids:
        return {"created": 0, "updated": 0, "review_kept": 0, "stale": 0, "drafts_recalculated": 0}
    bounds = metric_service.date_bounds(db)
    special = calendar_service.special_days_by_store(db, store_ids=store_ids, start=bounds[0], end=bounds[1])
    grouped = metric_service.series_points(db, bounds[0], bounds[1], special=special)
    stores = {store.id: store for store in db.scalars(select(Store).where(Store.id.in_(store_ids))).all()}
    totals = {"created": 0, "updated": 0, "review_kept": 0, "stale": 0}
    for position, store_id in enumerate(store_ids, start=1):
        store = stores.get(store_id)
        series = grouped.get(store_id)
        if store is None or not series:
            continue
        outcome = _recompute_store(db, store, series, job.calendar_version)
        for key in totals:
            totals[key] += outcome.get(key, 0)
        db.flush()
        job.progress = {"stores_done": position, "stores_total": len(store_ids)}
        job.staging = {**(job.staging or {}), "checkpoint": dict(job.progress)}
        db.commit()
        if fail_at_store is not None and position >= fail_at_store:
            raise RuntimeError(f"模拟中断：已处理 {position} 家门店（可续跑）")
    draft_ids = [int(item) for item in ((job.staging or {}).get("draft_ids") or [])]
    drafts = 0
    for report_id in draft_ids:
        report = db.get(Report, report_id)
        if report is None or report.status == "published":
            continue
        revision = scope.get("revision_version")
        report_service.reassess(db, report_id, operator, version=revision)
        drafts += 1
        db.flush()
        db.commit()
    totals["drafts_recalculated"] = drafts
    return totals


def execute(db: Session, job: GenerationJob, *, operator: str, fail_at_store: int | None = None) -> GenerationJob:
    try:
        job.status = "running"
        job.stage = "applying"
        db.flush()
        db.commit()
        totals = _apply(db, job, operator=operator, fail_at_store=fail_at_store)
        scope = job.payload or {}
        job.staging = {
            **(job.staging or {}),
            "state": "committed",
            "result": {"summary": {**totals, "published_preserved": scope.get("published_report_ids") or []}},
        }
        job.status = "success"
        job.stage = "committed"
        job.log_text = (
            f"日历 v{job.calendar_version} 失效重算：异常新增 {totals['created']}、更新 {totals['updated']}、"
            f"保留复核 {totals['review_kept']}、标记失效 {totals['stale']}；"
            f"草稿重算 {totals.get('drafts_recalculated', 0)} 份；已发布保留原引用 "
            f"{len(scope.get('published_report_ids') or [])} 份"
        )
        db.flush()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 中断要可恢复
        db.rollback()
        job.status = "failed"
        job.stage = "applying"
        job.log_text = f"失效重算中断：{exc}"
        db.flush()
        db.commit()
    return job


def start(
    db: Session,
    *,
    revision: CalendarRevision,
    operator: str,
    fail_at_store: int | None = None,
) -> GenerationJob:
    existing = db.scalar(
        select(GenerationJob)
        .where(
            GenerationJob.kind == "recompute",
            GenerationJob.calendar_version == revision.version,
            GenerationJob.status == "success",
        )
        .order_by(GenerationJob.id)
    )
    if existing is not None:
        existing.idempotent_hit = True
        db.flush()
        db.commit()
        return existing
    store_ids = sorted(set(int(item) for item in ((revision.scope or {}).get("store_ids") or [])))
    impact = calendar_service.impacted_scope(db, store_ids)
    baseline = _capture_baseline(db, store_ids, impact["draft_report_ids"])
    job = GenerationJob(
        job_no=next_job_no(db, "recompute"),
        kind="recompute",
        calendar_version=revision.version,
        status="running",
        stage="staged",
        payload={
            "revision_version": revision.version,
            "summary": revision.summary,
            "store_ids": store_ids,
            "published_report_ids": impact["published_report_ids"],
        },
        staging=baseline,
    )
    db.add(job)
    db.flush()
    db.commit()
    return execute(db, job, operator=operator, fail_at_store=fail_at_store)


def resume(db: Session, job_id: int, *, operator: str, fail_at_store: int | None = None) -> GenerationJob:
    job = get_job(db, job_id)
    if job.status == "success":
        job.idempotent_hit = True
        db.flush()
        db.commit()
        return job
    baseline = (job.staging or {}).get("baseline") or job.staging
    if not baseline or baseline.get("state") != "staged":
        raise AppError("CONFLICT", 409, {"job_no": job.job_no, "message": "没有可恢复的完整旧版快照"})
    # 恢复目标是「任务开始时」的旧版，因此日历版本必须仍是同一个；版本变了就不续跑，避免新旧口径混算
    recorded = int(baseline.get("calendar_version") or 0)
    if recorded != calendar_service.current_version(db) or recorded != int(job.calendar_version or 0):
        raise AppError(
            "CONFLICT",
            409,
            {"job_no": job.job_no, "message": "日历版本已变化，请按当前规则重新发起失效重算"},
        )
    recovery = restore_baseline(db, baseline)
    job.recovered_from = job.id
    job.staging = {**baseline, "baseline": baseline, "recovered": recovery}
    job.progress = {}
    db.flush()
    db.commit()
    return execute(db, job, operator=operator, fail_at_store=fail_at_store)


def list_jobs(db: Session, *, limit: int = 20) -> dict:
    rows = db.scalars(select(GenerationJob).order_by(GenerationJob.id.desc()).limit(limit)).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": db.scalar(select(func.count()).select_from(GenerationJob)) or 0,
    }


def get_job(db: Session, job_id: int) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise not_found("generation_job", job_id)
    return job
