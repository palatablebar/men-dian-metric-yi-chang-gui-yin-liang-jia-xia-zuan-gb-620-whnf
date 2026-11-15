"""报告服务：日报/周报生成、发布、快照与导出。

日历口径：
- 生成报告时记录 `calendar_version`，快照里保留异常 id 列表与纳入/排除日期摘要；
- 日历规则更新后，**草稿报告失效重算**（标 invalidated + 影响范围），
  **已发布报告保留原引用**（snapshot / calendar_version 原样不动，只标记规则已变更）。
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    CALENDAR_DAY_TYPE_LABELS,
    METRIC_LABELS,
    REPORT_INVALIDATION_LABELS,
    REPORT_KIND_LABELS,
    REPORT_STATUS_LABELS,
    SEVERITY_LABELS,
)
from src.models.anomaly import Anomaly
from src.models.calendar import CalendarRevision, OperatingCalendar
from src.models.metric import MetricPoint
from src.models.report import Report
from src.models.store import Store
from src.services import calendar_service
from src.utils.errors import AppError, not_found
from src.utils.timeutil import iso_date, iso_utc, local_now, parse_date


def serialize(report: Report) -> dict:
    snapshot = report.snapshot or {}
    return {
        "id": report.id,
        "report_no": report.report_no,
        "kind": report.kind,
        "kind_label": REPORT_KIND_LABELS.get(report.kind, report.kind),
        "period_start": iso_date(report.period_start),
        "period_end": iso_date(report.period_end),
        "title": report.title,
        "status": report.status,
        "status_label": REPORT_STATUS_LABELS.get(report.status, report.status),
        "generated_by": report.generated_by,
        "anomaly_count": report.anomaly_count,
        "impact_total": round(report.impact_total, 2),
        "note": report.note,
        "snapshot": snapshot,
        "calendar_version": report.calendar_version,
        "invalidated": report.invalidated,
        "invalidated_reason": report.invalidated_reason,
        "invalidated_label": REPORT_INVALIDATION_LABELS.get(report.invalidated_reason or "", None),
        "invalidated_by_version": report.invalidated_by_version,
        "superseded_by": report.superseded_by,
        "created_at": iso_utc(report.created_at),
        "updated_at": iso_utc(report.updated_at),
    }


def next_report_no(db: Session) -> str:
    prefix = f"RP{local_now():%Y%m%d}"
    count = db.scalar(select(func.count()).select_from(Report).where(Report.report_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:04d}"


def _calendar_summary(db: Session, start: date, end: date, version: int | None = None) -> dict:
    rules_stmt = select(OperatingCalendar).where(
        OperatingCalendar.active.is_(True),
        OperatingCalendar.start_date <= end,
        OperatingCalendar.end_date >= start,
    )
    if version is not None:
        # 历史版本：只认在该版本时已存在的规则（seed_key / 创建版本 <= version）
        rules_stmt = rules_stmt.where(OperatingCalendar.calendar_version <= version)
    rules = db.scalars(rules_stmt).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    included_days = (end - start).days + 1
    excluded: dict[str, dict] = {}
    for rule in rules:
        cursor = max(rule.start_date, start)
        last = min(rule.end_date, end)
        while cursor <= last:
            entry = excluded.setdefault(
                cursor.isoformat(),
                {"date": cursor.isoformat(), "day_type": rule.day_type, "day_type_label": CALENDAR_DAY_TYPE_LABELS.get(rule.day_type, rule.day_type), "stores": []},
            )
            store = stores.get(rule.store_id)
            if store is not None:
                entry["stores"].append(store.code)
            cursor += timedelta(days=1)
    return {
        "period_days": included_days,
        "excluded_dates": [excluded[key] for key in sorted(excluded)],
        "excluded_day_count": len(excluded),
        "included_day_count": max(0, included_days - len(excluded)),
        "calendar_version": version if version is not None else calendar_service.current_version(db),
    }


def build_snapshot(db: Session, start: date, end: date, version: int | None = None) -> dict:
    rows = db.scalars(
        select(Anomaly).where(
            Anomaly.metric_date >= start,
            Anomaly.metric_date <= end,
            Anomaly.invalidated.is_(False),
        )
    ).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    severity = {"high": 0, "medium": 0, "low": 0}
    status = {"pending": 0, "confirmed": 0, "dismissed": 0}
    by_metric: dict[str, int] = {}
    drag: dict[str, dict] = {}
    for row in rows:
        severity[row.severity] = severity.get(row.severity, 0) + 1
        status[row.status] = status.get(row.status, 0) + 1
        by_metric[row.metric_key] = by_metric.get(row.metric_key, 0) + 1
        store = stores.get(row.store_id)
        key = store.name if store else str(row.store_id)
        entry = drag.setdefault(key, {"store": key, "code": store.code if store else "", "impact": 0.0, "count": 0})
        entry["impact"] += row.impact_amount
        entry["count"] += 1
    drag_rows = sorted(drag.values(), key=lambda item: item["impact"])[:5]
    bounds = db.execute(select(func.min(MetricPoint.stat_date), func.max(MetricPoint.stat_date))).one()
    calendar = _calendar_summary(db, start, end, version=version)
    # 报告内出现的异常实际用到的可比样本里，被运营日历排除的特殊日（按出现次数）
    baseline_exclusions: dict[str, int] = {}
    for row in rows:
        for item in (row.payload or {}).get("excluded_special_days", []):
            day = item.get("date")
            if day:
                baseline_exclusions[day] = baseline_exclusions.get(day, 0) + 1
    return {
        "period": {"start": iso_date(start), "end": iso_date(end)},
        "data_window": {"start": iso_date(bounds[0]), "end": iso_date(bounds[1])},
        "anomaly_ids": [row.id for row in rows],
        "anomaly_count": len(rows),
        "impact_total": round(sum(row.impact_amount for row in rows), 2),
        "severity": [
            {"key": key, "label": SEVERITY_LABELS[key], "count": severity.get(key, 0)} for key in ("high", "medium", "low")
        ],
        "review": [{"key": key, "count": value} for key, value in status.items()],
        "by_metric": [{"key": key, "label": METRIC_LABELS.get(key, key), "count": value} for key, value in sorted(by_metric.items())],
        "top_drag_stores": [
            {"store": item["store"], "code": item["code"], "impact": round(item["impact"], 2), "count": item["count"]}
            for item in drag_rows
        ],
        "calendar": calendar,
        "baseline_excluded_dates": sorted(baseline_exclusions),
        "method": "rolling median+MAD (window=28, |z|>=3.5, 同向 2 天, 特殊日不进基线)；LMDI 量价分解",
    }


def generate(db: Session, payload: dict, operator: str) -> Report:
    kind = payload.get("kind") or "weekly"
    end = parse_date(payload.get("period_end")) or local_now().date()
    if payload.get("period_start"):
        start = parse_date(payload.get("period_start")) or end - timedelta(days=6)
    else:
        start = end - timedelta(days=6 if kind == "weekly" else 0)
    if start > end:
        raise AppError("VALIDATION", 422, {"field": "period_start", "message": "开始日期不能晚于结束日期"})
    snapshot = build_snapshot(db, start, end)
    report = Report(
        report_no=next_report_no(db),
        kind=kind,
        period_start=start,
        period_end=end,
        title=f"蓝湾酒店集团 {start.isoformat()} ~ {end.isoformat()} 经营异常{'周报' if kind == 'weekly' else '日报'}",
        status="draft",
        generated_by=operator,
        anomaly_count=snapshot["anomaly_count"],
        impact_total=snapshot["impact_total"],
        note=payload.get("note"),
        snapshot=snapshot,
        calendar_version=int(snapshot.get("calendar", {}).get("calendar_version") or 0),
    )
    db.add(report)
    db.flush()
    return report


def list_reports(db: Session, *, kind: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    stmt = select(Report)
    count_stmt = select(func.count()).select_from(Report)
    if kind:
        stmt = stmt.where(Report.kind == kind)
        count_stmt = count_stmt.where(Report.kind == kind)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Report.id.desc()).limit(limit).offset(offset)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise not_found("report", report_id)
    return report


def publish(db: Session, report: Report, status: str, note: str | None) -> Report:
    if status == "published" and report.invalidated:
        # 日历规则已变更的草稿不能直接发布，先按当前日历重算，避免把旧口径发给区域经理
        raise AppError(
            "CONFLICT",
            409,
            {
                "report_no": report.report_no,
                "message": "草稿因日历规则变更已失效，请先按当前日历重算",
                "invalidated_by_version": report.invalidated_by_version,
            },
        )
    report.status = status
    if note is not None:
        report.note = note
    db.flush()
    return report


def reassess(db: Session, report_id: int, operator: str, version: int | None = None) -> dict:
    """草稿失效重算：按当前日历版本重建草稿快照；已发布报告不允许改写（保留原引用）。"""
    report = get_report(db, report_id)
    if report.status == "published":
        raise AppError("CONFLICT", 409, {"report_no": report.report_no, "message": "已发布报告保留原引用，不能重算"})
    snapshot = build_snapshot(db, report.period_start, report.period_end, version=version)
    previous_version = report.calendar_version
    report.snapshot = snapshot
    report.anomaly_count = snapshot["anomaly_count"]
    report.impact_total = snapshot["impact_total"]
    report.calendar_version = int(snapshot.get("calendar", {}).get("calendar_version") or 0)
    report.invalidated = False
    report.invalidated_reason = None
    report.generated_by = operator
    db.flush()
    return {
        "report": serialize(report),
        "previous_calendar_version": previous_version,
        "recalculated_at_version": report.calendar_version,
    }


def invalidation_impact(db: Session, version: int | None = None) -> dict:
    """失效影响范围：按日历版本列出受影响异常 / 草稿 / 已发布（保留原引用）。

    影响范围来自该版本的 `CalendarRevision.scope`（规则变更涉及的门店），
    因此即使重算已完成、失效标记被清除，也能回看这次变更影响了哪些对象。
    """
    current = calendar_service.current_version(db)
    target = version if version is not None else current
    revision = db.scalar(select(CalendarRevision).where(CalendarRevision.version == target))
    if revision is not None:
        store_ids = sorted(set(int(item) for item in ((revision.scope or {}).get("store_ids") or [])))
        summary = revision.summary
        action = revision.action
    else:
        store_ids = sorted(
            set(
                int(item)
                for item in db.scalars(
                    select(Anomaly.store_id).where(Anomaly.invalidated_by_version == target)
                ).all()
            )
        )
        summary = ""
        action = ""
    anomalies = (
        db.scalars(select(Anomaly).where(Anomaly.store_id.in_(store_ids)).order_by(Anomaly.id)).all()
        if store_ids
        else []
    )
    touched_anomaly_ids = {item.id for item in anomalies}
    drafts = []
    published = []
    if touched_anomaly_ids:
        for report in db.scalars(select(Report).order_by(Report.id)).all():
            snapshot_ids = set((report.snapshot or {}).get("anomaly_ids") or [])
            if not snapshot_ids & touched_anomaly_ids:
                continue
            if report.status == "published":
                published.append(report)
            else:
                drafts.append(report)
    pending = [item for item in anomalies if item.invalidated]
    reviewed = [item for item in anomalies if not item.invalidated and item.status != "pending"]
    return {
        "calendar_version": target,
        "current_version": current,
        "revision": calendar_service.serialize_revision(revision) if revision is not None else None,
        "summary": summary,
        "action": action,
        "anomalies": {
            "count": len(anomalies),
            "pending": len(pending),
            "reviewed_kept": len(reviewed),
            "ids": [item.id for item in anomalies],
            "items": [
                {
                    "id": item.id,
                    "store_id": item.store_id,
                    "metric_date": item.metric_date.isoformat(),
                    "metric_key": item.metric_key,
                    "status": item.status,
                    "invalidated": item.invalidated,
                    "reason": item.invalidated_reason,
                    "calendar_version": item.calendar_version,
                }
                for item in anomalies
            ],
        },
        "drafts": {
            "count": len(drafts),
            "ids": [item.id for item in drafts],
            "items": [
                {
                    "id": item.id,
                    "report_no": item.report_no,
                    "period": f"{item.period_start.isoformat()} ~ {item.period_end.isoformat()}",
                    "calendar_version": item.calendar_version,
                    "invalidated": item.invalidated,
                }
                for item in drafts
            ],
        },
        "published_preserved": {
            "count": len(published),
            "ids": [item.id for item in published],
            "items": [
                {
                    "id": item.id,
                    "report_no": item.report_no,
                    "period": f"{item.period_start.isoformat()} ~ {item.period_end.isoformat()}",
                    "calendar_version": item.calendar_version,
                    "note": "已发布报告保留原引用，不随日历变更改写",
                }
                for item in published
            ],
        },
    }
