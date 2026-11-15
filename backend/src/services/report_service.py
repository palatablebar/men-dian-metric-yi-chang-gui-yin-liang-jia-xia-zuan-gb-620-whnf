"""报告服务：日报/周报生成、发布、快照与导出。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import METRIC_LABELS, REPORT_KIND_LABELS, REPORT_STATUS_LABELS, SEVERITY_LABELS
from src.models.anomaly import Anomaly
from src.models.metric import MetricPoint
from src.models.report import Report
from src.models.store import Store
from src.utils.errors import AppError, not_found
from src.utils.timeutil import iso_date, iso_utc, local_now, parse_date


def serialize(report: Report) -> dict:
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
        "snapshot": report.snapshot or {},
        "created_at": iso_utc(report.created_at),
    }


def next_report_no(db: Session) -> str:
    prefix = f"RP{local_now():%Y%m%d}"
    count = db.scalar(select(func.count()).select_from(Report).where(Report.report_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:04d}"


def build_snapshot(db: Session, start: date, end: date) -> dict:
    rows = db.scalars(select(Anomaly).where(Anomaly.metric_date >= start, Anomaly.metric_date <= end)).all()
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
    return {
        "period": {"start": iso_date(start), "end": iso_date(end)},
        "data_window": {"start": iso_date(bounds[0]), "end": iso_date(bounds[1])},
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
        "method": "rolling median+MAD (window=28, |z|>=3.5, 同向 2 天)；LMDI 量价分解",
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
    report.status = status
    if note is not None:
        report.note = note
    db.flush()
    return report
