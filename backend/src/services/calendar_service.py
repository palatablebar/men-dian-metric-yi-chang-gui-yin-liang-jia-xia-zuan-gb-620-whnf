"""运营日历服务：规则 CRUD、按门店展开特殊日、版本管理、失效影响范围。

关键口径：
- 特殊日类型 `promo` / `renovating` / `closed` 一律**不进入常态基线**；
- 规则以「门店 + 生效日期区间」表达（`start_date` ~ `end_date` 含端点），可按门店查；
- 每次写操作产生新版本号（全局单调递增，从 1 开始），异常 / 归因 / 报告都记录版本；
- 规则变更后：受影响门店的未处理异常与草稿报告**失效重算**，已发布报告保留原引用；
- 同一版本重复执行幂等：重复调用 `change_version` 不会重复产生异常或报告。
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    CALENDAR_DAY_TYPE_LABELS,
    CALENDAR_DAY_TYPE_ORDER,
    CalendarDayType,
)
from src.models.anomaly import Anomaly
from src.models.calendar import CalendarRevision, OperatingCalendar
from src.models.metric import MetricPoint
from src.models.report import Report
from src.models.store import Store
from src.utils.errors import AppError, not_found
from src.utils.timeutil import iso_date, iso_utc, parse_date, utcnow

MAX_SPAN_DAYS = 366


# ---------------------------------------------------------------- 版本 / 序列化


def current_version(db: Session) -> int:
    return db.scalar(select(func.max(CalendarRevision.version))) or 0


def next_version(db: Session) -> int:
    return current_version(db) + 1


def serialize_rule(rule: OperatingCalendar, store: Store | None = None) -> dict:
    return {
        "id": rule.id,
        "store_id": rule.store_id,
        "store_code": store.code if store else None,
        "store_name": store.name if store else None,
        "day_type": rule.day_type,
        "day_type_label": CALENDAR_DAY_TYPE_LABELS.get(rule.day_type, rule.day_type),
        "start_date": iso_date(rule.start_date),
        "end_date": iso_date(rule.end_date),
        "days": (rule.end_date - rule.start_date).days + 1,
        "label": rule.label,
        "note": rule.note,
        "active": rule.active,
        "calendar_version": rule.calendar_version,
        "created_by": rule.created_by,
        "created_at": iso_utc(rule.created_at),
        "updated_at": iso_utc(rule.updated_at),
    }


def serialize_revision(revision: CalendarRevision) -> dict:
    return {
        "id": revision.id,
        "version": revision.version,
        "action": revision.action,
        "actor_email": revision.actor_email,
        "summary": revision.summary,
        "scope": revision.scope or {},
        "created_at": iso_utc(revision.created_at),
    }


# ---------------------------------------------------------------- 规则查询 / 展开


def _active_rules(db: Session, store_ids: list[int] | None = None) -> list[OperatingCalendar]:
    stmt = select(OperatingCalendar).where(OperatingCalendar.active.is_(True))
    if store_ids is not None:
        if not store_ids:
            return []
        stmt = stmt.where(OperatingCalendar.store_id.in_(store_ids))
    return list(db.scalars(stmt.order_by(OperatingCalendar.store_id, OperatingCalendar.start_date)).all())


def special_days_by_store(
    db: Session,
    *,
    store_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[int, dict[str, str]]:
    """{store_id: {iso_date: day_type}}；只包含生效规则覆盖的日期。"""
    mapping: dict[int, dict[str, str]] = {}
    for rule in _active_rules(db, store_ids):
        cursor = rule.start_date
        while cursor <= rule.end_date:
            if (start is None or cursor >= start) and (end is None or cursor <= end):
                mapping.setdefault(rule.store_id, {})[cursor.isoformat()] = rule.day_type
            cursor += timedelta(days=1)
    return mapping


def store_calendar(db: Session, store_id: int) -> dict:
    """单店日历视图：全部规则 + 逐日纳入/排除明细（供页面查看纳入和排除日期）。"""
    store = db.get(Store, store_id)
    if store is None:
        raise not_found("store", store_id)
    rules = list(
        db.scalars(
            select(OperatingCalendar)
            .where(OperatingCalendar.store_id == store_id)
            .order_by(OperatingCalendar.start_date, OperatingCalendar.id)
        ).all()
    )
    expanded = special_days_by_store(db, store_ids=[store_id])
    bounds = db.execute(
        select(func.min(MetricPoint.stat_date), func.max(MetricPoint.stat_date)).where(
            MetricPoint.store_id == store_id
        )
    ).one()
    days: list[dict] = []
    if bounds and bounds[0]:
        cursor = bounds[0]
        while cursor <= bounds[1]:
            day_type = expanded.get(store_id, {}).get(cursor.isoformat())
            days.append(
                {
                    "date": cursor.isoformat(),
                    "included": day_type is None,
                    "day_type": day_type,
                    "day_type_label": CALENDAR_DAY_TYPE_LABELS.get(day_type, None) if day_type else "常态日",
                }
            )
            cursor += timedelta(days=1)
    included_days = [item["date"] for item in days if item["included"]]
    excluded_days = [item["date"] for item in days if not item["included"]]
    return {
        "store_id": store_id,
        "store_code": store.code,
        "store_name": store.name,
        "calendar_version": current_version(db),
        "data_window": {
            "start": iso_date(bounds[0]) if bounds and bounds[0] else None,
            "end": iso_date(bounds[1]) if bounds and bounds[1] else None,
        },
        "rules": [serialize_rule(rule, store) for rule in rules],
        "special_days": [
            {"date": day, "day_type": day_type, "day_type_label": CALENDAR_DAY_TYPE_LABELS.get(day_type, day_type)}
            for day, day_type in sorted(expanded.get(store_id, {}).items())
        ],
        "days": days,
        "included_day_count": len(included_days),
        "excluded_day_count": len(excluded_days),
        "included_days": included_days,
        "excluded_days": excluded_days,
    }


def list_rules(
    db: Session,
    *,
    store_id: int | None = None,
    day_type: str | None = None,
    active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    stmt = select(OperatingCalendar)
    count_stmt = select(func.count()).select_from(OperatingCalendar)
    conditions = []
    if store_id:
        conditions.append(OperatingCalendar.store_id == store_id)
    if day_type:
        conditions.append(OperatingCalendar.day_type == day_type)
    if active is not None:
        conditions.append(OperatingCalendar.active.is_(active))
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(OperatingCalendar.start_date.desc(), OperatingCalendar.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    return {
        "items": [serialize_rule(row, stores.get(row.store_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "calendar_version": current_version(db),
        "day_types": [
            {"key": key, "label": CALENDAR_DAY_TYPE_LABELS[key]} for key in CALENDAR_DAY_TYPE_ORDER
        ],
    }


def list_revisions(db: Session, limit: int = 20) -> dict:
    rows = db.scalars(select(CalendarRevision).order_by(CalendarRevision.version.desc()).limit(limit)).all()
    return {
        "items": [serialize_revision(row) for row in rows],
        "total": db.scalar(select(func.count()).select_from(CalendarRevision)) or 0,
        "calendar_version": current_version(db),
    }


# ---------------------------------------------------------------- 写入（带版本）


def _preview_range(rule: OperatingCalendar, store: Store | None) -> dict:
    return {
        "store_id": rule.store_id,
        "store_code": store.code if store else None,
        "day_type": rule.day_type,
        "start_date": iso_date(rule.start_date),
        "end_date": iso_date(rule.end_date),
        "days": (rule.end_date - rule.start_date).days + 1,
    }


def change_version(
    db: Session,
    *,
    action: str,
    actor_email: str,
    summary: str,
    scope: dict,
) -> CalendarRevision:
    revision = CalendarRevision(
        version=next_version(db),
        action=action,
        actor_email=actor_email,
        summary=summary[:200],
        scope=scope,
    )
    db.add(revision)
    db.flush()
    return revision


def create_rule(db: Session, payload: dict, actor: str) -> tuple[OperatingCalendar, CalendarRevision]:
    store = db.get(Store, payload["store_id"])
    if store is None:
        raise not_found("store", payload["store_id"])
    start = parse_date(payload.get("start_date"))
    end = parse_date(payload.get("end_date")) or start
    if start is None or end is None:
        raise AppError("VALIDATION", 422, {"field": "start_date"})
    if end < start:
        raise AppError("VALIDATION", 422, {"field": "end_date", "message": "结束日期不能早于开始日期"})
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        raise AppError("VALIDATION", 422, {"field": "end_date", "message": f"单条规则最长 {MAX_SPAN_DAYS} 天"})
    day_type = payload.get("day_type") or CalendarDayType.PROMO.value
    duplicate = db.scalar(
        select(OperatingCalendar).where(
            OperatingCalendar.store_id == store.id,
            OperatingCalendar.day_type == day_type,
            OperatingCalendar.start_date == start,
            OperatingCalendar.end_date == end,
        )
    )
    if duplicate is not None:
        raise AppError("CONFLICT", 409, {"field": "start_date", "message": "同门店同类型同区间规则已存在"})
    rule = OperatingCalendar(
        store_id=store.id,
        day_type=day_type,
        start_date=start,
        end_date=end,
        label=payload.get("label") or CALENDAR_DAY_TYPE_LABELS.get(day_type, day_type),
        note=payload.get("note"),
        active=bool(payload.get("active", True)),
        created_by=actor,
    )
    db.add(rule)
    db.flush()
    revision = change_version(
        db,
        action="create",
        actor_email=actor,
        summary=f"新增特殊日：{store.name} {start.isoformat()}~{end.isoformat()} {CALENDAR_DAY_TYPE_LABELS.get(day_type, day_type)}",
        scope={"kind": "rule", "rule_ids": [rule.id], "store_ids": [store.id],
               "ranges": [_preview_range(rule, store)], "dates": _expand_dates(start, end)},
    )
    rule.calendar_version = revision.version
    db.flush()
    return rule, revision


def update_rule(db: Session, rule_id: int, payload: dict, actor: str) -> tuple[OperatingCalendar, CalendarRevision]:
    rule = db.get(OperatingCalendar, rule_id)
    if rule is None:
        raise not_found("calendar_rule", rule_id)
    store = db.get(Store, rule.store_id)
    before = _preview_range(rule, store)
    start = parse_date(payload.get("start_date")) or rule.start_date
    end = parse_date(payload.get("end_date")) or rule.end_date
    if end < start:
        raise AppError("VALIDATION", 422, {"field": "end_date", "message": "结束日期不能早于开始日期"})
    rule.start_date = start
    rule.end_date = end
    for field in ("day_type", "label", "note"):
        if payload.get(field) is not None:
            setattr(rule, field, payload[field])
    if payload.get("active") is not None:
        rule.active = bool(payload["active"])
    db.flush()
    after = _preview_range(rule, store)
    revision = change_version(
        db,
        action="update",
        actor_email=actor,
        summary=f"修改特殊日：{store.name if store else rule.store_id} {before['start_date']}~{before['end_date']} → {after['start_date']}~{after['end_date']}",
        scope={
            "kind": "rule",
            "rule_ids": [rule.id],
            "store_ids": [rule.store_id],
            "ranges": [before, after],
            "dates": sorted(set(_expand_dates(start, end)) | set(_expand_dates(parse_date(before["start_date"]), parse_date(before["end_date"])))),
        },
    )
    rule.calendar_version = revision.version
    db.flush()
    return rule, revision


def deactivate_rule(db: Session, rule_id: int, actor: str) -> tuple[OperatingCalendar, CalendarRevision]:
    rule = db.get(OperatingCalendar, rule_id)
    if rule is None:
        raise not_found("calendar_rule", rule_id)
    if not rule.active:
        raise AppError("CONFLICT", 409, {"message": "规则已停用"})
    store = db.get(Store, rule.store_id)
    rule.active = False
    db.flush()
    revision = change_version(
        db,
        action="deactivate",
        actor_email=actor,
        summary=f"停用特殊日：{store.name if store else rule.store_id} {rule.start_date.isoformat()}~{rule.end_date.isoformat()}",
        scope={
            "kind": "rule",
            "rule_ids": [rule.id],
            "store_ids": [rule.store_id],
            "ranges": [_preview_range(rule, store)],
            "dates": _expand_dates(rule.start_date, rule.end_date),
        },
    )
    rule.calendar_version = revision.version
    db.flush()
    return rule, revision


def _expand_dates(start: date | None, end: date | None) -> list[str]:
    if start is None or end is None:
        return []
    out: list[str] = []
    cursor = start
    while cursor <= end:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


# ---------------------------------------------------------------- 失效影响范围


def impacted_scope(db: Session, store_ids: list[int]) -> dict:
    """规则变更会影响到的异常 / 草稿报告 / 已发布报告（保留引用）。

    报表只要：区间内存在受影响门店的异常，或快照引用了受影响异常，即纳入范围；
    再按报告状态分成「草稿重算」与「已发布保留原引用」两档。
    """
    if not store_ids:
        return {"store_ids": [], "anomaly_ids": [], "draft_report_ids": [], "published_report_ids": []}
    anomaly_ids = list(
        db.scalars(select(Anomaly.id).where(Anomaly.store_id.in_(store_ids)).order_by(Anomaly.id)).all()
    )
    anomaly_rows = {
        row.id: row
        for row in db.scalars(select(Anomaly).where(Anomaly.store_id.in_(store_ids))).all()
    }
    draft_ids: list[int] = []
    published_ids: list[int] = []
    for report in db.scalars(select(Report).order_by(Report.id)).all():
        snapshot = report.snapshot or {}
        snapshot_ids = set(snapshot.get("anomaly_ids") or [])
        cited = bool(snapshot_ids & set(anomaly_ids))
        in_period = any(
            report.period_start <= row.metric_date <= report.period_end for row in anomaly_rows.values()
        )
        has_window_overlap = any(
            report.period_start <= parse_date((row.payload or {}).get("window_end")) <= report.period_end
            or report.period_start <= parse_date((row.payload or {}).get("window_start")) <= report.period_end
            for row in anomaly_rows.values()
        )
        if not (cited or in_period or has_window_overlap):
            continue
        if report.status == "published":
            published_ids.append(report.id)
        else:
            draft_ids.append(report.id)
    return {
        "store_ids": sorted(store_ids),
        "anomaly_ids": anomaly_ids,
        "draft_report_ids": sorted(set(draft_ids)),
        "published_report_ids": sorted(set(published_ids)),
    }


def invalidate_scope(db: Session, scope: dict, version: int) -> dict:
    """把影响范围内的异常标记失效、草稿报告标记失效；已发布报告一律不动。"""
    anomaly_ids = scope.get("anomaly_ids") or []
    draft_ids = scope.get("draft_report_ids") or []
    published = set(scope.get("published_report_ids") or [])
    anomalies = db.scalars(select(Anomaly).where(Anomaly.id.in_(anomaly_ids))).all() if anomaly_ids else []
    marked_anomalies = 0
    for anomaly in anomalies:
        if anomaly.status != "pending":
            # 已复核的异常：保留人工结论，但标记为「规则已变更，待重算核对」
            anomaly.invalidated_reason = "calendar_changed_reviewed"
            anomaly.invalidated_by_version = version
            continue
        anomaly.invalidated = True
        anomaly.invalidated_reason = "calendar_changed"
        anomaly.invalidated_by_version = version
        marked_anomalies += 1
    marked_reports = 0
    reports = db.scalars(select(Report).where(Report.id.in_(draft_ids))).all() if draft_ids else []
    for report in reports:
        if report.id in published:
            continue
        report.invalidated = True
        report.invalidated_reason = "calendar_changed"
        report.invalidated_by_version = version
        marked_reports += 1
    db.flush()
    return {
        "anomalies_marked": marked_anomalies,
        "anomalies_reviewed_kept": len(anomalies) - marked_anomalies,
        "drafts_invalidated": marked_reports,
        "published_preserved": sorted(published),
    }


def day_type_options() -> list[dict]:
    return [
        {
            "key": key,
            "label": CALENDAR_DAY_TYPE_LABELS[key],
            "excluded_from_baseline": True,
        }
        for key in CALENDAR_DAY_TYPE_ORDER
    ]


def version_info(db: Session) -> dict:
    version = current_version(db)
    revision = db.scalar(select(CalendarRevision).where(CalendarRevision.version == version))
    return {
        "calendar_version": version,
        "rules_active": db.scalar(
            select(func.count()).select_from(OperatingCalendar).where(OperatingCalendar.active.is_(True))
        )
        or 0,
        "latest_revision": serialize_revision(revision) if revision else None,
        "generated_at": utcnow().isoformat(timespec="seconds") + "Z",
    }
