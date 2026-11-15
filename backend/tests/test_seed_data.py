"""演示数据集不变量：规模、头条异常数值、渠道一致性、确定性。"""
from __future__ import annotations

from scripts.demo_data import HEADLINE_DATE, HEADLINE_IMPACT, build_dataset

from src.services import decompose, detection

CACHE: dict = {}


def dataset() -> dict:
    if "data" not in CACHE:
        CACHE["data"] = build_dataset()
    return CACHE["data"]


def aggregate_series(points: list[dict], store_code: str) -> list[dict]:
    days: dict = {}
    for point in points:
        if point["store_code"] != store_code:
            continue
        entry = days.setdefault(
            point["stat_date"],
            {"date": point["stat_date"].isoformat(), "rooms_available": point["rooms_available"], "rooms_sold": 0, "revenue": 0.0, "is_weekend": point["is_weekend"]},
        )
        entry["rooms_sold"] += point["rooms_sold"]
        entry["revenue"] += point["revenue"]
    series = []
    for stat_date, entry in sorted(days.items()):
        revenue = round(entry["revenue"], 2)
        series.append(
            {
                "date": entry["date"],
                "rooms_available": entry["rooms_available"],
                "rooms_sold": entry["rooms_sold"],
                "occupancy": round(entry["rooms_sold"] / entry["rooms_available"], 6),
                "adr": round(revenue / entry["rooms_sold"], 6),
                "revenue": revenue,
                "is_weekend": entry["is_weekend"],
            }
        )
    return series


def test_dataset_shape():
    data = dataset()
    assert data["meta"]["stores"] == 120
    assert data["meta"]["days"] == 90
    assert data["meta"]["points"] == 32400
    assert len(data["events"]) == 37


def test_headline_anomaly_matches_acceptance():
    data = dataset()
    series = aggregate_series(data["points"], "LB-HD-001")
    hits = detection.detect_series(series, "rev")["hits"]
    headline = [hit for hit in hits if hit["date"] == HEADLINE_DATE.isoformat()]
    assert len(headline) == 1
    hit = headline[0]
    assert round(hit["robust_z"], 1) == -4.2
    assert abs(hit["impact_amount"] - HEADLINE_IMPACT) < 2_000
    result = decompose.decompose(hit["baseline_triple"], hit["current_triple"])
    shares = result["shares"]
    assert abs(shares["adr"] - 0.62) < 0.03
    assert abs(shares["occ"] - 0.31) < 0.03
    assert abs(shares["rooms"] - 0.07) < 0.02


def test_channel_revenue_sums_to_store_revenue():
    data = dataset()
    series = aggregate_series(data["points"], "LB-HD-001")
    total = sum(point["revenue"] for point in data["points"] if point["store_code"] == "LB-HD-001")
    assert abs(total - sum(item["revenue"] for item in series)) < 1.0


def test_detection_finds_exactly_the_planned_events():
    data = dataset()
    found = set()
    for store in {point["store_code"] for point in data["points"]}:
        for hit in detection.detect_series(aggregate_series(data["points"], store), "rev")["hits"]:
            found.add((store, hit["date"]))
    planned = {(item["store_code"], item["metric_date"]) for item in data["events"]}
    assert found == planned
    assert len(found) == 37


def test_dataset_is_deterministic():
    first = build_dataset()
    second = build_dataset()
    assert first["meta"] == second["meta"]
    assert first["events"] == second["events"]
    assert first["points"][:50] == second["points"][:50]
