"""算法 A（稳健异常检测）单测：正常触发 / 方向延续 / 周末分层 / 退化基线 / 确定性。"""
from __future__ import annotations

from datetime import date, timedelta

from src.services import detection

START = date(2026, 8, 1)


def _series(values: list[float], weekend_at: set[int] | None = None) -> list[dict]:
    weekend_at = weekend_at or set()
    rows = []
    for index, value in enumerate(values):
        rows.append(
            {
                "date": (START + timedelta(days=index)).isoformat(),
                "revenue": float(value),
                "rooms_sold": 100,
                "rooms_available": 150,
                "adr": round(float(value) / 100, 4),
                "occupancy": round(100 / 150, 6),
                "is_weekend": index in weekend_at,
            }
        )
    return rows


def _flat_series(days: int = 60, base: float = 1000.0) -> list[float]:
    pattern = [-3, -2, -1, 1, 2, 3]
    return [base + pattern[index % len(pattern)] * 10 for index in range(days)]


def test_detects_two_day_downward_dip():
    values = _flat_series()
    values[44] = 930.0     # 前一日同向小跌
    values[45] = 820.0     # 触发日
    series = _series(values)
    result = detection.detect_series(series, "rev")
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["date"] == series[45]["date"]
    assert hit["robust_z"] < -3.5
    assert hit["direction"] == "down"
    assert hit["impact_amount"] < 0
    assert hit["severity"] in ("high", "medium", "low")


def test_requires_direction_persistence():
    values = _flat_series()
    values[45] = 700.0  # 单日暴跌，但前一日正常
    series = _series(values)
    result = detection.detect_series(series, "rev")
    assert result["hits"] == []
    reasons = {item["reason"] for item in result["skipped"]}
    assert "no_direction_persist" in reasons


def test_threshold_is_respected():
    values = _flat_series()
    values[44] = 960.0
    values[45] = 940.0  # 波动不够大
    series = _series(values)
    assert detection.detect_series(series, "rev")["hits"] == []


def test_weekend_stratification_keeps_baseline_separate():
    values = []
    for index in range(60):
        if index % 7 in (5, 6):
            values.append(1600.0 + (index % 5) * 8)
        else:
            values.append(1000.0 + (index % 5) * 8)
    series = _series(values, weekend_at={index for index in range(60) if index % 7 in (5, 6)})
    result = detection.detect_series(series, "rev")
    assert result["hits"] == []
    for skipped in result["skipped"]:
        assert skipped.get("reason") in ("insufficient_baseline",)
    # 用全体混合基线会把周末的正常高点误报，证明分层确实生效
    mixed = detection.detect_series(series, "rev", stratify=False)
    assert len(mixed["hits"]) >= 2


def test_degenerate_baseline_is_skipped():
    values = [1000.0] * 60
    series = _series(values)
    result = detection.detect_series(series, "rev")
    assert result["hits"] == []
    assert any(item["reason"] == "degenerate_baseline" for item in result["skipped"])


def test_insufficient_baseline_is_skipped():
    series = _series(_flat_series(days=8))
    result = detection.detect_series(series, "rev")
    assert result["hits"] == []
    assert all(item["reason"] == "insufficient_baseline" for item in result["skipped"])


def test_mad_zero_falls_back_to_mean_absolute_deviation():
    values = [1000.0] * 40 + [1002.0, 1000.0, 1004.0, 999.0]
    center, mad, basis = detection.robust_stats(values)
    assert center == 1000.0
    assert mad > 0
    assert basis in ("mad", "mean-abs-dev")


def test_severity_uses_amount_and_z():
    assert detection.severity_of(-4.25, -10.0) == "medium"
    assert detection.severity_of(-5.5, -10.0) == "high"
    assert detection.severity_of(-3.6, -90_000.0) == "high"
    assert detection.severity_of(-3.6, -10.0) == "low"


def test_deterministic_output():
    values = _flat_series()
    values[44] = 930.0
    values[45] = 820.0
    series = _series(values)
    first = detection.detect_series(series, "rev")
    second = detection.detect_series(series, "rev")
    assert first == second


def _mark_special(series: list[dict], dates: set[str], day_type: str = "promo") -> list[dict]:
    return [
        {**row, "is_special": row["date"] in dates, "special_type": day_type if row["date"] in dates else None}
        for row in series
    ]


def test_special_days_are_excluded_from_baseline_but_current_still_evaluated():
    values = _flat_series(days=60)
    values[44] = 930.0
    values[45] = 820.0  # 两日同向下跌 → 正常应触发
    series = _series(values)
    # 窗口内的一个普通工作日被标为大促：只影响可比样本，不影响当期判定
    special_dates = {series[40]["date"]}
    marked = _mark_special(series, special_dates)
    result = detection.detect_series(marked, "rev")
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["date"] == series[45]["date"]
    assert hit["special_day"] is False
    assert series[40]["date"] not in hit["window_dates"]
    assert series[40]["date"] in {item["date"] for item in hit["excluded_special_days"]}
    assert hit["window_samples"] == len(hit["window_dates"])
    assert hit["sample_key"]
    # 同期样本仍够 10 条（排除 1 天后从更早处补齐）
    assert hit["window_samples"] == 28


def test_special_day_does_not_create_direction_persistence():
    values = _flat_series(days=60)
    values[44] = 930.0  # 特殊日的小跌
    values[45] = 820.0  # 当期暴跌
    series = _series(values)
    marked = _mark_special(series, {series[44]["date"]})
    result = detection.detect_series(marked, "rev")
    # 特殊日不能充当「方向延续」的前一观测，因此不硬判为异常
    assert result["hits"] == []


def test_special_day_itself_still_uses_real_result_if_it_hits():
    values = _flat_series(days=60)
    values[44] = 930.0
    values[45] = 700.0
    series = _series(values)
    marked = _mark_special(series, {series[45]["date"]}, "closed")
    result = detection.detect_series(marked, "rev")
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    # 当期观测是真实经营结果：不清零、不平滑
    assert hit["observed"] == 700.0
    assert hit["current_triple"]["revenue"] == 700.0
    assert hit["special_day"] is True


def test_single_special_day_does_not_create_persistence():
    values = _flat_series(days=60)
    values[45] = 700.0  # 单日暴跌
    series = _series(values)
    marked = _mark_special(series, {series[45]["date"]})
    result = detection.detect_series(marked, "rev")
    assert result["hits"] == []
