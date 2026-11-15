"""运营日历 API 契约测试：权限、版本推进、失效范围、幂等续跑（SQLite + TestClient）。

不依赖 MySQL / Redis：临时把 engine 绑到内存库，并关闭启动 seed。
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.constants.enums import Role
from src.constants.roles import CALENDAR_WRITE_ROLES
from src.models import Base
from src.models.anomaly import Anomaly
from src.models.metric import MetricPoint
from src.models.store import Store
from src.utils.security import create_access_token


_FACTORY = {}


def _session() -> Session:
    return _FACTORY["session"]()


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    _FACTORY["session"] = factory
    db = factory()
    _seed(db)
    db.close()

    import src.config.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", factory)

    import src.config.app as app_module

    monkeypatch.setattr(app_module, "_run_seed_once", lambda: None)
    app = app_module.create_app()
    # 直接用内存库会话替换依赖，避免中间件/依赖再用旧 engine
    app.dependency_overrides[database.get_db] = lambda: factory()
    return TestClient(app)


def _seed(db: Session) -> None:
    store = Store(code="T-001", name="测试店", region="华东", city="上海", room_count=200)
    db.add(store)
    db.flush()
    start = date(2026, 8, 1)
    for offset in range(70):
        day = start + timedelta(days=offset)
        weekend = day.weekday() >= 5
        rooms = 200
        sold = int(round(rooms * (0.82 if weekend else 0.78) * (1 + (offset % 5 - 2) * 0.004)))
        if offset == 58:
            sold = int(round(sold * 0.92))
        if offset == 59:
            sold = int(round(sold * 0.70))
        adr = 1000.0
        for channel, share in (("ota", 0.5), ("direct", 0.3), ("corp", 0.2)):
            channel_sold = sold if channel == "corp" else int(round(sold * share))
            db.add(
                MetricPoint(
                    store_id=store.id,
                    stat_date=day,
                    channel=channel,
                    rooms_available=rooms,
                    rooms_sold=channel_sold,
                    occupancy=round(channel_sold / rooms, 6),
                    adr=adr,
                    revenue=round(adr * channel_sold, 2),
                    is_weekend=weekend,
                    room_type_mix={"大床房": 0.5, "双床房": 0.36, "套房": 0.14},
                )
            )
    db.commit()


def _token(role: str) -> dict:
    token, _ = create_access_token("user@anomalyattr.io", role)
    return {"Authorization": f"Bearer {token}"}


def test_calendar_read_is_open_to_all_roles_write_is_admin_only(client):
    response = client.get("/api/calendar", headers=_token(Role.VIEWER.value))
    assert response.status_code == 200
    assert response.json()["calendar_version"] == 0

    payload = {
        "store_id": 1,
        "day_type": "promo",
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
        "label": "国庆大促",
    }
    assert client.post("/api/calendar", json=payload, headers=_token(Role.VIEWER.value)).status_code == 403
    assert client.post("/api/calendar", json=payload, headers=_token(Role.ANALYST.value)).status_code == 403
    assert Role.ADMIN.value in CALENDAR_WRITE_ROLES
    assert client.post("/api/calendar", json=payload, headers=_token(Role.ADMIN.value)).status_code == 201


def test_invalid_range_is_422_and_duplicate_409(client):
    payload = {
        "store_id": 1,
        "day_type": "closed",
        "start_date": "2026-10-10",
        "end_date": "2026-10-01",
    }
    assert client.post("/api/calendar", json=payload, headers=_token(Role.ADMIN.value)).status_code == 422
    ok = dict(payload, end_date="2026-10-10")
    assert client.post("/api/calendar", json=ok, headers=_token(Role.ADMIN.value)).status_code == 201
    assert client.post("/api/calendar", json=ok, headers=_token(Role.ADMIN.value)).status_code == 409


def test_rule_change_advances_version_and_reports_impact(client):
    run = client.post(
        "/api/runs",
        json={"metrics": ["rev"], "trigger": "manual"},
        headers=_token(Role.ANALYST.value),
    )
    assert run.status_code == 201
    anomaly_count = run.json()["anomaly_count"]
    assert anomaly_count >= 1

    report = client.post(
        "/api/reports",
        json={"kind": "weekly", "period_start": "2026-09-28", "period_end": "2026-10-09"},
        headers=_token(Role.ADMIN.value),
    )
    assert report.status_code == 201
    report_id = report.json()["id"]
    assert report.json()["calendar_version"] == 0
    assert report.json()["anomaly_count"] >= 1

    response = client.post(
        "/api/calendar",
        json={
            "store_id": 1,
            "day_type": "renovating",
            "start_date": "2026-08-20",
            "end_date": "2026-08-22",
            "label": "改造",
        },
        headers=_token(Role.ADMIN.value),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["calendar_version"] == 1
    assert body["job"]["status"] == "success"
    assert body["impact"]["draft_report_ids"] == [report_id]
    assert body["published_preserved"] == []

    detail = client.get(f"/api/reports/{report_id}", headers=_token(Role.VIEWER.value)).json()
    assert detail["calendar_version"] == 1, "草稿已按新日历版本重算"
    assert detail["invalidated"] is False
    assert body["invalidated"]["drafts_invalidated"] >= 1
    assert body["job"]["summary"]["drafts_recalculated"] >= 1

    impact = client.get("/api/reports/impact/invalidation?version=1", headers=_token(Role.VIEWER.value)).json()
    assert impact["current_version"] == 1
    assert impact["anomalies"]["count"] >= 1


def test_published_report_keeps_original_reference(client):
    assert client.post(
        "/api/runs", json={"metrics": ["rev"], "trigger": "manual"}, headers=_token(Role.ANALYST.value)
    ).status_code == 201
    report = client.post(
        "/api/reports",
        json={"kind": "weekly", "period_start": "2026-09-28", "period_end": "2026-10-09"},
        headers=_token(Role.ADMIN.value),
    ).json()
    assert report["anomaly_count"] >= 1
    published = client.patch(
        f"/api/reports/{report['id']}", json={"status": "published"}, headers=_token(Role.ADMIN.value)
    )
    assert published.status_code == 200
    snapshot = published.json()["snapshot"]

    client.post(
        "/api/calendar",
        json={"store_id": 1, "day_type": "promo", "start_date": "2026-08-15", "end_date": "2026-08-16"},
        headers=_token(Role.ADMIN.value),
    )
    detail = client.get(f"/api/reports/{report['id']}", headers=_token(Role.ADMIN.value)).json()
    assert detail["snapshot"] == snapshot, "已发布报告保留原引用"
    assert detail["calendar_version"] == report["calendar_version"]
    assert detail["status"] == "published"
    response = client.post(f"/api/reports/{report['id']}/reassess", headers=_token(Role.ADMIN.value))
    assert response.status_code == 409


def test_store_calendar_lists_included_and_excluded_dates(client):
    client.post(
        "/api/calendar",
        json={"store_id": 1, "day_type": "renovating", "start_date": "2026-08-20", "end_date": "2026-08-22"},
        headers=_token(Role.ADMIN.value),
    )
    data = client.get("/api/calendar/store/1", headers=_token(Role.VIEWER.value)).json()
    assert data["calendar_version"] == 1
    assert "2026-08-20" in data["excluded_days"]
    assert "2026-08-21" in data["excluded_days"]
    assert "2026-08-19" in data["included_days"]
    assert data["excluded_day_count"] == 3
    assert data["included_day_count"] + data["excluded_day_count"] == len(data["days"])
    assert any(item["included"] is False and item["day_type"] == "renovating" for item in data["days"])
    assert client.get("/api/calendar/store/9999", headers=_token(Role.VIEWER.value)).status_code == 404


def test_invalidated_draft_cannot_be_published_until_reassessed(client):
    assert client.post(
        "/api/runs", json={"metrics": ["rev"], "trigger": "manual"}, headers=_token(Role.ANALYST.value)
    ).status_code == 201
    report = client.post(
        "/api/reports",
        json={"kind": "weekly", "period_start": "2026-09-28", "period_end": "2026-10-09"},
        headers=_token(Role.ADMIN.value),
    ).json()
    db = _session()
    try:
        from src.models.report import Report

        row = db.get(Report, report["id"])
        row.invalidated = True
        row.invalidated_reason = "calendar_changed"
        row.invalidated_by_version = 1
        db.commit()
    finally:
        db.close()
    blocked = client.patch(
        f"/api/reports/{report['id']}", json={"status": "published"}, headers=_token(Role.ADMIN.value)
    )
    assert blocked.status_code == 409
    ok = client.post(f"/api/reports/{report['id']}/reassess", headers=_token(Role.ADMIN.value))
    assert ok.status_code == 200
    published = client.patch(
        f"/api/reports/{report['id']}", json={"status": "published"}, headers=_token(Role.ADMIN.value)
    )
    assert published.status_code == 200


def test_rerun_same_version_is_idempotent(client):
    first = client.post(
        "/api/calendar",
        json={"store_id": 1, "day_type": "promo", "start_date": "2026-08-10", "end_date": "2026-08-11"},
        headers=_token(Role.ADMIN.value),
    ).json()
    assert first["job"]["status"] == "success"
    with_next = client.post(
        "/api/calendar",
        json={"store_id": 1, "day_type": "closed", "start_date": "2026-09-15", "end_date": "2026-09-15"},
        headers=_token(Role.ADMIN.value),
    ).json()
    jobs = client.get("/api/calendar/jobs", headers=_token(Role.VIEWER.value)).json()["items"]
    versions = {job["calendar_version"] for job in jobs}
    assert with_next["calendar_version"] == 2
    assert {1, 2}.issubset(versions)
    anomalies = client.get("/api/anomalies?include_invalidated=true&limit=200", headers=_token(Role.VIEWER.value)).json()
    keys = [(row["store_id"], row["metric_date"], row["metric_key"]) for row in anomalies["items"]]
    assert len(keys) == len(set(keys)), "重跑不得新增重复异常"
