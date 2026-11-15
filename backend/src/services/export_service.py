"""导出服务：异常清单 / 归因明细 / 报告 CSV（UTF-8 BOM，Excel 直开）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import (
    CHANNEL_LABELS,
    DIRECTION_LABELS,
    METRIC_LABELS,
    REPORT_KIND_LABELS,
    REVIEW_STATUS_LABELS,
    SEVERITY_LABELS,
)
from src.models.anomaly import Anomaly
from src.models.attribution import Attribution
from src.models.report import Report
from src.models.store import Store
from src.utils.csv_export import to_csv


def anomalies_csv(db: Session, store_id: int | None = None, severity: str | None = None) -> bytes:
    stmt = select(Anomaly)
    if store_id:
        stmt = stmt.where(Anomaly.store_id == store_id)
    if severity:
        stmt = stmt.where(Anomaly.severity == severity)
    rows = db.scalars(stmt.order_by(Anomaly.metric_date.desc(), Anomaly.id)).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    headers = [
        "门店编码", "门店", "区域", "指标日期", "指标", "观测值", "稳健基线", "MAD",
        "稳健z", "方向", "严重度", "影响金额(元)", "处理状态", "复核人", "复核备注",
    ]
    body = []
    for row in rows:
        store = stores.get(row.store_id)
        body.append(
            [
                store.code if store else "",
                store.name if store else "",
                store.region if store else "",
                row.metric_date.isoformat(),
                METRIC_LABELS.get(row.metric_key, row.metric_key),
                f"{row.observed:.2f}",
                f"{row.baseline:.2f}",
                f"{row.mad:.2f}",
                f"{row.robust_z:.4f}",
                DIRECTION_LABELS.get(row.direction, row.direction),
                SEVERITY_LABELS.get(row.severity, row.severity),
                f"{row.impact_amount:.2f}",
                REVIEW_STATUS_LABELS.get(row.status, row.status),
                row.reviewer or "",
                row.review_note or "",
            ]
        )
    return to_csv(headers, body)


def attributions_csv(db: Session) -> bytes:
    rows = db.scalars(select(Attribution).order_by(Attribution.id)).all()
    anomalies = {row.id: row for row in db.scalars(select(Anomaly)).all()}
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    headers = [
        "门店编码", "门店", "指标日期", "指标", "方法", "基线营收", "当期营收", "总变动",
        "ADR 贡献", "OCC 贡献", "ROOMS 贡献", "ADR 占比", "OCC 占比", "ROOMS 占比", "残差", "结论",
    ]
    body = []
    for row in rows:
        anomaly = anomalies.get(row.anomaly_id)
        store = stores.get(row.store_id)
        body.append(
            [
                store.code if store else "",
                store.name if store else "",
                anomaly.metric_date.isoformat() if anomaly else "",
                METRIC_LABELS.get(anomaly.metric_key, "") if anomaly else "",
                row.method,
                f"{row.base_rev:.2f}",
                f"{row.cur_rev:.2f}",
                f"{row.total_delta:.2f}",
                f"{row.adr_part:.2f}",
                f"{row.occ_part:.2f}",
                f"{row.rooms_part:.2f}",
                "" if row.adr_share is None else f"{row.adr_share:.4f}",
                "" if row.occ_share is None else f"{row.occ_share:.4f}",
                "" if row.rooms_share is None else f"{row.rooms_share:.4f}",
                f"{row.residual:.4f}",
                row.narrative,
            ]
        )
    return to_csv(headers, body)


def report_csv(db: Session, report: Report) -> bytes:
    snapshot = report.snapshot or {}
    headers = ["项", "值"]
    rows: list[list[object]] = [
        ["报告编号", report.report_no],
        ["报告类型", REPORT_KIND_LABELS.get(report.kind, report.kind)],
        ["统计区间", f"{report.period_start.isoformat()} ~ {report.period_end.isoformat()}"],
        ["异常起数", report.anomaly_count],
        ["影响金额合计(元)", f"{report.impact_total:.2f}"],
        ["生成人", report.generated_by],
        ["数据窗口", f"{snapshot.get('data_window', {}).get('start', '')} ~ {snapshot.get('data_window', {}).get('end', '')}"],
        ["口径", snapshot.get("method", "")],
        ["", ""],
        ["严重度", "起数"],
    ]
    for item in snapshot.get("severity", []):
        rows.append([item.get("label", ""), item.get("count", 0)])
    rows.append(["", ""])
    rows.append(["指标", "起数"])
    for item in snapshot.get("by_metric", []):
        rows.append([item.get("label", ""), item.get("count", 0)])
    rows.append(["", ""])
    rows.append(["拖累门店", "影响金额(元)"])
    for item in snapshot.get("top_drag_stores", []):
        rows.append([item.get("store", ""), item.get("impact", 0)])
    return to_csv(headers, rows)


def channels_csv(db: Session) -> bytes:
    rows = db.scalars(select(Attribution)).all()
    headers = ["门店", "指标日期", "维度", "分组", "当期", "基线", "变动", "贡献占比"]
    body = []
    for row in rows:
        store = db.get(Store, row.store_id)
        dimensions = row.dimensions or {}
        for key in ("channel", "store", "room_type"):
            block = dimensions.get(key) or {}
            for item in block.get("rows", []):
                body.append(
                    [
                        store.name if store else "",
                        row.anomaly_id,
                        block.get("label", key),
                        item.get("key", ""),
                        item.get("current", ""),
                        item.get("base", ""),
                        item.get("delta", ""),
                        "" if item.get("contribution") is None else f"{item['contribution']:.4f}",
                    ]
                )
    return to_csv(headers, body)
