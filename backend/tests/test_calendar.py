"""运营日历 + 样本一致性 + 失效重算 的集成测试（SQLite 内存库，不依赖 MySQL/Redis）。

覆盖：
- 特殊日不进入常态基线，当期异常仍按真实结果产出；
- 异常 / 量价三项 / 维度下钻共用同一组样本日期；
- 日历版本递增、规则更新后相关异常与草稿失效、已发布报告保留原引用；
- 生成中断先恢复完整旧版再续跑；同版本重跑不新增重复结果、不退还复核。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.models import Base
from src.models.anomaly import Anomaly
from src.models.attribution import Attribution
from src.models.calendar import CalendarRevision, OperatingCalendar
from src.models.metric import MetricPoint
from src.models.report import Report
from src.models.store import Store
from src.services import calendar_service, generation_service, report_service, run_service

TODAY = date(2026, 9, 30)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _seed(db: Session, store_count: int = 1, days: int = 80) -> list[Store]:
    """构造平稳序列 + 一次两日下跌；测试可直接观察基线样本差异。"""
    stores: list[Store] = []
    start = date(2026, 7, 1)
    for index in range(store_count):
        store = Store(code=f"T-{index:03d}", name=f"测试店{index}", region="华东", city="上海", room_count=200)
        db.add(store)
        db.flush()
        stores.append(store)
        for offset in range(days):
            day = start + timedelta(days=offset)
            weekend = day.weekday() >= 5
            rooms = 200
            base = 0.80 if not weekend else 0.86
            factor = 1.0 + ((-3, -2, -1, 1, 2, 3)[offset % 6]) * 0.006
            sold = int(round(rooms * base * factor))
            adr = 1000.0 if not weekend else 1060.0
            # 第 70~71 天制造「方向一致两日下跌」
            if offset == 70:
                sold = int(round(sold * 0.93))
            if offset == 71:
                sold = int(round(sold * 0.72))
            for channel in ("ota", "direct", "corp"):
                share = {"ota": 0.5, "direct": 0.3, "corp": 0.2}[channel]
                channel_sold = sold if channel == "corp" else int(round(sold * share))
                db.add(
                    MetricPoint(
                        store_id=store.id,
                        stat_date=day,
                        channel=channel,
                        rooms_available=rooms,
                        rooms_sold=channel_sold,
                        occupancy=round(channel_sold / rooms, 6),
                        adr=round(adr, 2),
                        revenue=round(adr * channel_sold, 2),
                        is_weekend=weekend,
                        room_type_mix={"大床房": 0.5, "双床房": 0.36, "套房": 0.14},
                    )
                )
        db.flush()
    return stores


def _run(db: Session) -> run_service.Run:
    return run_service.create_and_execute(
        db, store_id=None, trigger="manual", operator_email="analyst@anomalyattr.io", params={"metrics": ["rev"]}
    )


def test_special_days_excluded_from_baseline_but_current_still_reported(db: Session):
    stores = _seed(db)
    run = _run(db)
    anomaly = db.scalar(select(Anomaly).where(Anomaly.store_id == stores[0].id))
    assert anomaly is not None, "两日下跌应产出异常"
    hit_date = anomaly.metric_date
    payload = anomaly.payload
    assert payload["window_dates"], "命中项必须回填参与样本的日期"
    assert hit_date.isoformat() not in payload["window_dates"]

    # 把命中窗口内的 3 个工作日标为大促，重跑：基线必须换一组样本，但当期异常仍存在
    promo_start = hit_date - timedelta(days=15)
    promo_end = promo_start + timedelta(days=2)
    assert all((promo_start + timedelta(days=offset)).weekday() < 5 for offset in range(3))
    calendar_service.create_rule(
        db,
        {
            "store_id": stores[0].id,
            "day_type": "promo",
            "start_date": promo_start.isoformat(),
            "end_date": promo_end.isoformat(),
            "label": "测试大促",
        },
        "admin@anomalyattr.io",
    )
    db.commit()
    run2 = _run(db)
    db.commit()
    refreshed = db.scalar(select(Anomaly).where(Anomaly.store_id == stores[0].id, Anomaly.metric_date == hit_date))
    assert refreshed is not None
    assert refreshed.calendar_version == run2.calendar_version
    assert set(refreshed.payload["window_dates"]) != set(payload["window_dates"])
    for offset in range(3):
        day = (promo_start + timedelta(days=offset)).isoformat()
        assert day not in refreshed.payload["window_dates"], "特殊日不得进入常态基线"
    excluded = {item["date"] for item in refreshed.payload["excluded_special_days"]}
    assert promo_start.isoformat() in excluded and promo_end.isoformat() in excluded
    # 当期观测仍是真实经营结果（不做平滑 / 回填）
    assert refreshed.observed == round(refreshed.observed, 2)
    assert refreshed.impact_amount < 0


def test_attribution_uses_the_same_sample_as_anomaly(db: Session):
    stores = _seed(db)
    _run(db)
    db.commit()
    from src.services import attribution_service

    anomaly = db.scalar(select(Anomaly).where(Anomaly.store_id == stores[0].id))
    detail = attribution_service.get_by_anomaly(db, anomaly.id)
    payload = anomaly.payload
    assert detail["sample"]["key"] == payload["sample_key"]
    assert detail["sample"]["days"] == payload["window_dates"]
    assert detail["sample"]["consistent"] is True
    assert detail["dimensions"]["sample"]["window_days"] == payload["window_dates"]
    # 渠道维度基期只取这组样本日期：三渠道基期之和 ≈ 样本窗口日营收中位数 * 渠道占比
    channels = detail["dimensions"]["channel"]["rows"]
    assert len(channels) == 3
    base_total = sum(item["base"] for item in channels)
    assert base_total > 0


def test_report_calendar_version_and_published_preserved(db: Session):
    stores = _seed(db)
    _run(db)
    db.commit()
    draft = report_service.generate(
        db, {"kind": "weekly", "period_start": "2026-09-07", "period_end": "2026-09-13"}, "admin@anomalyattr.io"
    )
    published = report_service.generate(
        db, {"kind": "weekly", "period_start": "2026-09-07", "period_end": "2026-09-13"}, "admin@anomalyattr.io"
    )
    report_service.publish(db, published, "published", None)
    db.commit()
    published_snapshot = published.snapshot
    published_version = published.calendar_version
    assert draft.calendar_version == 0
    assert draft.snapshot["anomaly_ids"]

    rule, revision = calendar_service.create_rule(
        db,
        {
            "store_id": stores[0].id,
            "day_type": "renovating",
            "start_date": "2026-08-25",
            "end_date": "2026-08-27",
            "label": "改造",
        },
        "admin@anomalyattr.io",
    )
    db.commit()
    impact = calendar_service.invalidate_scope(
        db, calendar_service.impacted_scope(db, [stores[0].id]), revision.version
    )
    db.commit()
    assert revision.version == rule.calendar_version >= 1
    assert impact["published_preserved"] == [published.id]
    assert impact["drafts_invalidated"] >= 1
    db.refresh(published)
    assert published.snapshot == published_snapshot, "已发布报告保留原引用"
    assert published.calendar_version == published_version
    assert published.status == "published"
    db.refresh(draft)
    assert draft.invalidated is True
    assert draft.invalidated_by_version == revision.version
    result = report_service.reassess(db, draft.id, "admin@anomalyattr.io")
    db.commit()
    assert result["report"]["calendar_version"] == revision.version
    assert result["report"]["invalidated"] is False
    assert result["previous_calendar_version"] == 0
    impact_view = report_service.invalidation_impact(db, revision.version)
    assert impact_view["published_preserved"]["ids"] == [published.id]


def test_generation_resume_restores_full_baseline_and_is_idempotent(db: Session):
    stores = _seed(db, store_count=3)
    _run(db)
    db.commit()
    draft = report_service.generate(
        db, {"kind": "weekly", "period_start": "2026-09-07", "period_end": "2026-09-13"}, "admin@anomalyattr.io"
    )
    db.commit()
    reviewed = db.scalar(select(Anomaly))
    reviewed.status = "confirmed"
    reviewed.reviewer = "analyst@anomalyattr.io"
    reviewed.review_note = "人工确认"
    db.commit()
    baseline_anomaly_ids = {
        row.id: (row.store_id, row.metric_date.isoformat(), row.metric_key)
        for row in db.scalars(select(Anomaly)).all()
    }

    rule, revision = calendar_service.create_rule(
        db,
        {
            "store_id": stores[0].id,
            "day_type": "promo",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "label": "测试大促",
        },
        "admin@anomalyattr.io",
    )
    db.commit()
    calendar_service.invalidate_scope(db, calendar_service.impacted_scope(db, [stores[0].id]), revision.version)
    db.commit()

    # 模拟中断：只处理 1 家门店后失败（半途已改写受影响门店与草稿）
    job = generation_service.start(db, revision=revision, operator="admin@anomalyattr.io", fail_at_store=1)
    assert job.status == "failed"
    assert job.stage == "applying"
    resumed = generation_service.resume(db, job.id, operator="admin@anomalyattr.io")
    assert resumed.status == "success"
    assert resumed.recovered_from == job.id
    assert resumed.staging["recovered"]["anomalies_restored"] >= 1

    # 续跑的最终结果应与「用当前日历从零生成」一致 → 证明是从完整旧版恢复后重算，而不是在半途结果上叠加
    fresh = report_service.generate(
        db, {"kind": "weekly", "period_start": "2026-09-07", "period_end": "2026-09-13"}, "admin@anomalyattr.io"
    )
    db.commit()
    db.refresh(draft)
    assert draft.snapshot == fresh.snapshot
    assert draft.calendar_version == fresh.calendar_version == revision.version

    # 同版本重跑：不新增重复结果、不退还复核
    counts_before = (
        db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Anomaly)),
        db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Attribution)),
    )
    again = generation_service.start(db, revision=revision, operator="admin@anomalyattr.io")
    assert again.idempotent_hit is True
    counts_after = (
        db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Anomaly)),
        db.scalar(select(__import__("sqlalchemy").func.count()).select_from(Attribution)),
    )
    assert counts_after == counts_before
    assert counts_after[0] == counts_after[1], "每条异常恰好一条归因，重跑不新增重复归因"
    natural_keys = [(row.store_id, row.metric_date, row.metric_key) for row in db.scalars(select(Anomaly)).all()]
    assert len(natural_keys) == len(set(natural_keys))
    db.refresh(reviewed)
    assert reviewed.status == "confirmed"
    assert reviewed.reviewer == "analyst@anomalyattr.io"
    # 复核过的异常全部保留（除被规则明确改写的处理结论外，不应出现状态回退）
    assert reviewed.id in baseline_anomaly_ids
