"""总览：门店/指标规模、异常与影响金额、严重度分布、拖累门店 Top、趋势。"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.constants.enums import (
    METRIC_LABELS,
    REPORT_STATUS_LABELS,
    REVIEW_STATUS_LABELS,
    RUN_STATUS_LABELS,
    SEVERITY_LABELS,
    STORE_STATUS_LABELS,
)
from src.models.anomaly import Anomaly
from src.models.metric import MetricPoint
from src.models.report import Report
from src.models.run import Run
from src.models.store import Store
from src.utils.timeutil import local_now


def worker_alive() -> bool:
    try:
        import time

        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
        value = client.get(f"{settings.app_name}:worker:heartbeat")
        return bool(value) and (time.time() - float(value)) < 120
    except Exception:
        return False


def overview(db: Session) -> dict:
    stores_total = db.scalar(select(func.count()).select_from(Store)) or 0
    points_total = db.scalar(select(func.count()).select_from(MetricPoint)) or 0
    active = Anomaly.invalidated.is_(False)
    anomalies_total = db.scalar(select(func.count()).select_from(Anomaly).where(active)) or 0
    pending_total = (
        db.scalar(select(func.count()).select_from(Anomaly).where(Anomaly.status == "pending", active)) or 0
    )
    impacted_total = db.scalar(select(func.count()).select_from(Anomaly).where(Anomaly.invalidated.is_(True))) or 0
    impact_total = db.scalar(select(func.sum(Anomaly.impact_amount)).where(active)) or 0.0
    impact_pending = (
        db.scalar(select(func.sum(Anomaly.impact_amount)).where(Anomaly.status == "pending", active)) or 0.0
    )
    severity_rows = db.execute(select(Anomaly.severity, func.count()).where(active).group_by(Anomaly.severity)).all()
    status_rows = db.execute(select(Anomaly.status, func.count()).where(active).group_by(Anomaly.status)).all()
    metric_rows = db.execute(select(Anomaly.metric_key, func.count()).where(active).group_by(Anomaly.metric_key)).all()
    store_status_rows = db.execute(select(Store.status, func.count()).group_by(Store.status)).all()
    region_rows = db.execute(select(Store.region, func.count()).group_by(Store.region)).all()
    bounds = db.execute(select(func.min(MetricPoint.stat_date), func.max(MetricPoint.stat_date))).one()
    latest_run = db.scalar(select(Run).order_by(Run.id.desc()).limit(1))
    latest_report = db.scalar(select(Report).order_by(Report.id.desc()).limit(1))

    drag_rows = db.execute(
        select(Anomaly.store_id, func.sum(Anomaly.impact_amount), func.count())
        .where(active)
        .group_by(Anomaly.store_id)
        .order_by(func.sum(Anomaly.impact_amount))
        .limit(6)
    ).all()
    stores = {store.id: store for store in db.scalars(select(Store)).all()}
    top_drag = [
        {
            "store_id": store_id,
            "store_name": stores[store_id].name if store_id in stores else str(store_id),
            "store_code": stores[store_id].code if store_id in stores else "",
            "region": stores[store_id].region if store_id in stores else "",
            "impact": round(float(impact or 0.0), 2),
            "count": count,
        }
        for store_id, impact, count in drag_rows
    ]

    date_rows = db.execute(
        select(Anomaly.metric_date, func.count(), func.sum(Anomaly.impact_amount))
        .where(active)
        .group_by(Anomaly.metric_date)
        .order_by(Anomaly.metric_date.desc())
        .limit(10)
    ).all()
    trend = [
        {"date": stat_date.isoformat(), "count": count, "impact": round(float(impact or 0.0), 2)}
        for stat_date, count, impact in sorted(date_rows, key=lambda item: item[0])
    ]

    reviewed = sum(count for key, count in status_rows if key != "pending")
    return {
        "stores_total": stores_total,
        "points_total": points_total,
        "days": (bounds[1] - bounds[0]).days + 1 if bounds and bounds[0] else 0,
        "data_window": {
            "start": bounds[0].isoformat() if bounds and bounds[0] else None,
            "end": bounds[1].isoformat() if bounds and bounds[1] else None,
        },
        "anomalies_total": anomalies_total,
        "invalidated_total": impacted_total,
        "pending_total": pending_total,
        "reviewed_total": reviewed,
        "impact_total": round(float(impact_total), 2),
        "impact_pending": round(float(impact_pending), 2),
        "worker_alive": worker_alive(),
        "severity": [
            {"key": key, "label": SEVERITY_LABELS.get(key, key), "count": count}
            for key, count in sorted(
                severity_rows,
                key=lambda item: ["high", "medium", "low"].index(item[0]) if item[0] in ("high", "medium", "low") else 9,
            )
        ],
        "review": [
            {"key": key, "label": REVIEW_STATUS_LABELS.get(key, key), "count": count}
            for key, count in sorted(status_rows)
        ],
        "metrics": [
            {"key": key, "label": METRIC_LABELS.get(key, key), "count": count} for key, count in sorted(metric_rows)
        ],
        "store_status": [
            {"key": key, "label": STORE_STATUS_LABELS.get(key, key), "count": count}
            for key, count in sorted(store_status_rows)
        ],
        "regions": [{"region": region, "count": count} for region, count in sorted(region_rows)],
        "top_drag": top_drag,
        "trend": trend,
        "latest_run": {
            "id": latest_run.id,
            "run_no": latest_run.run_no,
            "status": latest_run.status,
            "status_label": RUN_STATUS_LABELS.get(latest_run.status, latest_run.status),
            "started_at": latest_run.started_at.isoformat(timespec="seconds") + "Z" if latest_run.started_at else None,
            "anomaly_count": latest_run.anomaly_count,
            "store_count": latest_run.store_count,
            "impact_total": (latest_run.metrics or {}).get("impact_total", 0),
        }
        if latest_run
        else None,
        "latest_report": {
            "id": latest_report.id,
            "report_no": latest_report.report_no,
            "status_label": REPORT_STATUS_LABELS.get(latest_report.status, latest_report.status),
            "period": f"{latest_report.period_start.isoformat()} ~ {latest_report.period_end.isoformat()}",
            "anomaly_count": latest_report.anomaly_count,
            "impact_total": round(latest_report.impact_total, 2),
        }
        if latest_report
        else None,
        "generated_at": local_now().isoformat(timespec="seconds"),
        "horizon_days": 7,
        "since": (local_now().date() - timedelta(days=0)).isoformat(),
    }
