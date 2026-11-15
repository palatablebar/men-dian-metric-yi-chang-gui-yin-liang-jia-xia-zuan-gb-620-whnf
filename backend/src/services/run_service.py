"""检测运行服务：加载序列 → 算法 A 检测 → 落异常 → 生成归因 → 汇总指标。

运营日历：检测前先取当前日历版本，特殊日不进入基线（见 `detection`）。
中断恢复：命中结果先写入 `run.metrics["staging"]`（含完整旧版快照），提交时才落库；
续跑时先核对 staging 完整性，不新增重复异常、不让已复核异常退回待处理。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import METRIC_LABELS
from src.models.anomaly import Anomaly
from src.models.metric import MetricPoint
from src.models.run import Run
from src.models.store import Store
from src.services import attribution_service, calendar_service, detection, metric_service
from src.utils.errors import AppError
from src.utils.timeutil import iso_utc, local_now, utcnow

DEFAULT_PARAMS = {"metrics": ["rev"], "window": 28, "threshold": 3.5, "persist_z": 1.5, "stratify": True}


def serialize(run: Run, store_name: str | None = None) -> dict:
    metrics = run.metrics or {}
    staging = metrics.get("staging") or {}
    return {
        "id": run.id,
        "run_no": run.run_no,
        "store_id": run.store_id,
        "store_name": store_name,
        "trigger": run.trigger,
        "status": run.status,
        "operator_email": run.operator_email,
        "store_count": run.store_count,
        "point_count": run.point_count,
        "anomaly_count": run.anomaly_count,
        "params": run.params or {},
        "metrics": metrics,
        "log_text": run.log_text,
        "calendar_version": run.calendar_version,
        "staging_state": staging.get("state") or "none",
        "resumable": run.status in ("running", "failed") and bool(staging),
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
    }


def next_run_no(db: Session) -> str:
    prefix = f"DT{local_now():%Y%m%d}"
    count = db.scalar(select(func.count()).select_from(Run).where(Run.run_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:04d}"


def _normalize_params(payload: dict | None) -> dict:
    params = dict(DEFAULT_PARAMS)
    for key, value in (payload or {}).items():
        if value is None:
            continue
        params[key] = value
    metrics = [item for item in params.get("metrics") or ["rev"] if item in METRIC_LABELS]
    params["metrics"] = metrics or ["rev"]
    return params


def _collect_hits(db: Session, run: Run, params: dict, calendar_version: int) -> dict:
    """纯计算阶段：只读取数据，输出 staging（不写异常 / 归因）。"""
    stores = db.scalars(select(Store).order_by(Store.code)).all()
    if run.store_id:
        stores = [store for store in stores if store.id == run.store_id]
    bounds = metric_service.date_bounds(db)
    special = calendar_service.special_days_by_store(db, start=bounds[0], end=bounds[1])
    grouped = metric_service.series_points(db, bounds[0], bounds[1], run.store_id, special=special)
    point_count = db.scalar(select(func.count()).select_from(MetricPoint)) or 0

    staging: dict = {
        "state": "complete",
        "calendar_version": calendar_version,
        "store_count": len(stores),
        "point_count": point_count,
        "stores": {},
        "special_days": {str(key): value for key, value in special.items()},
    }
    skipped_reasons: dict[str, int] = {}
    by_metric: dict[str, int] = {}
    evaluated_store_ids: list[int] = []
    for store in stores:
        series = grouped.get(store.id)
        if not series:
            continue
        evaluated_store_ids.append(store.id)
        for metric_key in params["metrics"]:
            result = detection.detect_series(
                series,
                metric_key,
                window=params["window"],
                threshold=params["threshold"],
                persist_z=params["persist_z"],
                stratify=params["stratify"],
            )
            for reason in result["skipped"]:
                skipped_reasons[reason["reason"]] = skipped_reasons.get(reason["reason"], 0) + 1
            for hit in result["hits"]:
                staging["stores"].setdefault(str(store.id), []).append(
                    {
                        "metric_date": hit["date"],
                        "metric_key": metric_key,
                        "observed": hit["observed"],
                        "baseline": hit["baseline"],
                        "mad": hit["mad"],
                        "robust_z": hit["robust_z"],
                        "direction": hit["direction"],
                        "severity": hit["severity"],
                        "impact_amount": hit["impact_amount"],
                        "windows": hit["window_dates"],
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
                            "calendar_version": calendar_version,
                            "sample_key": hit["sample_key"],
                            "special_day": hit.get("special_day", False),
                            "store_code": store.code,
                        },
                    }
                )
                by_metric[metric_key] = by_metric.get(metric_key, 0) + 1
    staging["skipped"] = skipped_reasons
    staging["special_days_in_effect"] = sum(len(days) for days in special.values())
    staging["by_metric"] = by_metric
    staging["store_ids"] = evaluated_store_ids
    return staging


def _restore_from_staging(db: Session, run: Run) -> int:
    """续跑前校验：staging 必须完整，否则不续跑（避免半份结果提交）。"""
    staging = (run.metrics or {}).get("staging") or {}
    if not staging or staging.get("state") != "complete":
        raise AppError("CONFLICT", 409, {"run_no": run.run_no, "message": "上次结果不完整，需重新发起检测"})
    if int(staging.get("calendar_version", -1)) != int(run.calendar_version):
        raise AppError("CONFLICT", 409, {"run_no": run.run_no, "message": "日历规则已变化，请重新发起检测"})
    return len(staging.get("stores") or {})


def _commit_staging(db: Session, run: Run, staging: dict) -> dict:
    """把 staging 一次性落库：异常 upsert、归因幂等生成、失效重算标记清理。"""
    from src.services import anomaly_service as anomaly_svc

    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    created = updated = reviewed_kept = 0
    hit_total = 0
    by_severity = {"high": 0, "medium": 0, "low": 0}
    z_values: list[float] = []
    seen_keys: set[tuple[int, str, str]] = set()
    for store_key, hits in (staging.get("stores") or {}).items():
        store_id = int(store_key)
        store = stores.get(store_id)
        if store is None:
            continue
        for hit in hits:
            metric_date = date.fromisoformat(hit["metric_date"])
            seen_keys.add((store_id, hit["metric_date"], hit["metric_key"]))
            payload = {
                "store_id": store_id,
                "metric_date": metric_date,
                "metric_key": hit["metric_key"],
                "observed": hit["observed"],
                "baseline": hit["baseline"],
                "mad": hit["mad"],
                "robust_z": hit["robust_z"],
                "direction": hit["direction"],
                "severity": hit["severity"],
                "impact_amount": hit["impact_amount"],
                "run_id": run.id,
                "status": "pending",
                "payload": hit["payload"],
                "calendar_version": int(staging.get("calendar_version") or 0),
            }
            anomaly, is_new = anomaly_svc.ensure_anomaly(db, payload)
            created += 1 if is_new else 0
            updated += 0 if is_new else 1
            if not is_new and anomaly.status != "pending":
                reviewed_kept += 1
            anomaly.invalidated = False
            anomaly.invalidated_reason = None
            anomaly.invalidated_by_version = None
            hit_total += 1
            by_severity[anomaly.severity] = by_severity.get(anomaly.severity, 0) + 1
            z_values.append(abs(anomaly.robust_z))
            attribution_service.build(db, anomaly, store)

    # 日历规则变更后本批次不再命中的旧异常：标失效（不删除，保留审计痕迹）
    target_store_ids = [int(key) for key in (staging.get("stores") or {}).keys()]
    target_store_ids += [int(key) for key in (staging.get("store_ids") or [])]
    target_store_ids = sorted(set(target_store_ids))
    if not target_store_ids:
        return {
            "created": created,
            "updated": updated,
            "reviewed_kept": reviewed_kept,
            "hit_total": hit_total,
            "by_severity": by_severity,
            "by_metric": staging.get("by_metric") or {},
            "z_values": z_values,
            "impact_total": 0.0,
            "stale_marked": 0,
            "skipped": staging.get("skipped") or {},
            "special_days_in_effect": staging.get("special_days_in_effect", 0),
        }
    # 只有「日历版本变化导致本批次不再命中」的旧异常才标失效（不删除，保留审计痕迹）；
    # 用户调阈值做的探索性检测不会把别的日历版本下的结果整批作废。
    stale = db.scalars(select(Anomaly).where(Anomaly.store_id.in_(target_store_ids))).all()
    stale_marked = 0
    metric_keys = set((staging.get("by_metric") or {}).keys()) or {"rev"}
    for anomaly in stale:
        key = (anomaly.store_id, anomaly.metric_date.isoformat(), anomaly.metric_key)
        if key in seen_keys:
            continue
        if anomaly.metric_key not in metric_keys:
            continue
        if anomaly.status != "pending":
            continue
        if anomaly.invalidated:
            continue
        if int(anomaly.calendar_version or 0) == int(run.calendar_version or 0):
            continue
        anomaly.invalidated = True
        anomaly.invalidated_reason = "not_in_recompute"
        anomaly.invalidated_by_version = run.calendar_version
        stale_marked += 1

    impact_total = db.scalar(
        select(func.sum(Anomaly.impact_amount)).where(Anomaly.run_id == run.id, Anomaly.invalidated.is_(False))
    ) or 0.0
    return {
        "created": created,
        "updated": updated,
        "reviewed_kept": reviewed_kept,
        "hit_total": hit_total,
        "by_severity": by_severity,
        "by_metric": staging.get("by_metric") or {},
        "z_values": z_values,
        "impact_total": round(float(impact_total), 2),
        "stale_marked": stale_marked,
        "skipped": staging.get("skipped") or {},
        "special_days_in_effect": staging.get("special_days_in_effect", 0),
    }


def execute(db: Session, run: Run, *, resume: bool = False) -> Run:
    run.status = "running"
    params = _normalize_params(run.params)
    run.params = params
    try:
        if resume:
            # 续跑必须沿用中断时的日历版本；版本已变化则要求重新发起（避免新旧口径混算）
            staging = (run.metrics or {}).get("staging") or {}
            recorded = int(staging.get("calendar_version", run.calendar_version) or 0)
            if recorded != calendar_service.current_version(db):
                raise AppError(
                    "CONFLICT",
                    409,
                    {"run_no": run.run_no, "message": "日历规则已变化，请重新发起检测"},
                )
            run.calendar_version = recorded
            _restore_from_staging(db, run)
        else:
            run.calendar_version = calendar_service.current_version(db)
            staging = _collect_hits(db, run, params, run.calendar_version)
            run.metrics = {**(run.metrics or {}), "staging": staging}
            db.flush()
        summary = _commit_staging(db, run, staging)
        run.store_count = int(staging.get("store_count") or 0)
        run.point_count = int(staging.get("point_count") or 0)
        run.anomaly_count = summary["hit_total"]
        metrics = {
            "metrics": params["metrics"],
            "window": params["window"],
            "threshold": params["threshold"],
            "persist_z": params["persist_z"],
            "stores": run.store_count,
            "points": run.point_count,
            "anomalies": summary["hit_total"],
            "created": summary["created"],
            "updated": summary["updated"],
            "reviewed_kept": summary["reviewed_kept"],
            "severity": summary["by_severity"],
            "by_metric": summary["by_metric"],
            "impact_total": summary["impact_total"],
            "max_abs_z": round(max(summary["z_values"]), 4) if summary["z_values"] else 0.0,
            "skipped": summary["skipped"],
            "special_days_in_effect": summary["special_days_in_effect"],
            "stale_marked": summary["stale_marked"],
            "calendar_version": run.calendar_version,
            "staging": {**staging, "state": "committed", "committed_at": utcnow().isoformat(timespec="seconds") + "Z"},
        }
        run.metrics = metrics
        run.status = "success" if summary["created"] or summary["updated"] else "partial"
        run.log_text = (
            f"检测 {run.store_count} 家门店 / {run.point_count} 条指标点；命中 {summary['hit_total']} 起异常"
            f"（新增 {summary['created']}、更新 {summary['updated']}、保留复核 {summary['reviewed_kept']}）；"
            f"high={summary['by_severity'].get('high', 0)} medium={summary['by_severity'].get('medium', 0)} "
            f"low={summary['by_severity'].get('low', 0)}；影响合计 {summary['impact_total']:,.0f} 元；"
            f"日历 v{run.calendar_version} 生效特殊日 {summary['special_days_in_effect']} 天（不进基线）；"
            f"口径：window={params['window']} threshold={params['threshold']} persist_z={params['persist_z']}"
        )
    except Exception as exc:  # noqa: BLE001 - 运行失败要留痕，不抛 500
        run.status = "failed"
        run.log_text = f"检测失败：{exc}"
        existing = (run.metrics or {}).get("staging") or {}
        run.metrics = {**(run.metrics or {}), "error": str(exc)[:300], "staging": existing}
    run.finished_at = utcnow()
    db.flush()
    return run

def resume_run(
    db: Session,
    run_id: int,
    *,
    operator_email: str,
    trigger: str = "manual",
) -> Run:
    """中断续跑：先恢复完整旧版 staging，再续算；同版本重复续跑不新增重复结果。"""
    run = db.get(Run, run_id)
    if run is None:
        raise AppError("NOT_FOUND", 404, {"entity": "run", "id": run_id})
    if run.status not in ("running", "failed"):
        raise AppError("CONFLICT", 409, {"run_no": run.run_no, "message": "该批次已结束，无需续跑"})
    staging = (run.metrics or {}).get("staging") or {}
    if not staging:
        raise AppError("CONFLICT", 409, {"run_no": run.run_no, "message": "没有可恢复的中间结果，请重新发起检测"})
    run.trigger = trigger
    run.operator_email = operator_email
    return execute(db, run, resume=True)


def create_and_execute(
    db: Session,
    *,
    store_id: int | None,
    trigger: str,
    operator_email: str,
    params: dict | None = None,
    seed_key: str | None = None,
    calendar_version: int | None = None,
) -> Run:
    if seed_key:
        existing = db.scalar(select(Run).where(Run.seed_key == seed_key))
        if existing is not None:
            return existing
    if store_id and db.get(Store, store_id) is None:
        raise AppError("NOT_FOUND", 404, {"entity": "store", "id": store_id})
    run = Run(
        run_no=next_run_no(db),
        store_id=store_id,
        trigger=trigger,
        status="running",
        operator_email=operator_email,
        params=_normalize_params(params),
        calendar_version=calendar_version if calendar_version is not None else calendar_service.current_version(db),
        seed_key=seed_key,
    )
    db.add(run)
    db.flush()
    return execute(db, run)


def list_runs(db: Session, *, status: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    stmt = select(Run)
    count_stmt = select(func.count()).select_from(Run)
    if status:
        stmt = stmt.where(Run.status == status)
        count_stmt = count_stmt.where(Run.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Run.id.desc()).limit(limit).offset(offset)).all()
    stores = {store.id: store.name for store in db.scalars(select(Store)).all()}
    return {
        "items": [serialize(row, stores.get(row.store_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_run(db: Session, run_id: int) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise AppError("NOT_FOUND", 404, {"entity": "run", "id": run_id})
    return run
