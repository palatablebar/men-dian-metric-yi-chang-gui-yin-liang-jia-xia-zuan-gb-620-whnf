"""算法 B（LMDI 量价分解 + 维度贡献）单测：正常 / 边界 / 确定性。"""
from __future__ import annotations

from src.services import decompose

BASE = {"adr": 1702.67, "occ": 0.875, "rooms": 240.0, "revenue": 357_560.0}
CURRENT = {"adr": 1435.42, "occ": 0.8, "rooms": 235.0, "revenue": 269_858.0}


def test_shares_sum_to_one_and_parts_reconstruct_delta():
    result = decompose.decompose(BASE, CURRENT)
    assert result["status"] == "ok"
    total = sum(result["parts"].values())
    assert abs(total - result["total_delta"]) < 20
    assert abs(sum(result["shares"].values()) - 1.0) < 0.005
    assert abs(result["residual"]) < 20


def test_factor_shares_order_and_sign():
    result = decompose.decompose(BASE, CURRENT)
    shares = result["shares"]
    # 占比 = 该因子变动 / 总变动，同号相除为正：三项都是正占比，合计 1
    assert shares["adr"] > 0 and shares["occ"] > 0 and shares["rooms"] > 0
    assert shares["adr"] == max(shares.values())
    assert abs(shares["adr"] + shares["occ"] + shares["rooms"] - 1.0) < 0.005


def test_flat_delta_has_no_shares():
    baseline = {"adr": 1000.0, "occ": 0.8, "rooms": 200.0, "revenue": 160_000.0}
    result = decompose.decompose(baseline, dict(baseline))
    assert result["status"] == "flat"
    assert result["parts"] == {"adr": 0.0, "occ": 0.0, "rooms": 0.0}
    assert result["shares"] == {"adr": None, "occ": None, "rooms": None}


def test_non_positive_factor_is_degenerate():
    bad = {"adr": 1000.0, "occ": 0.0, "rooms": 200.0, "revenue": 0.0}
    result = decompose.decompose(bad, CURRENT)
    assert result["status"] == "degenerate"
    assert result["parts"]["adr"] is None
    assert "非正因子" in result["reason"]


def test_rank_contributions_top_negative_and_positive():
    groups = [
        {"key": "OTA", "value": 120_000.0, "base": 180_000.0},
        {"key": "直连", "value": 90_000.0, "base": 96_000.0},
        {"key": "协议", "value": 40_000.0, "base": 36_000.0},
    ]
    result = decompose.rank_contributions(groups, -60_000.0)
    assert result["top_negative"][0]["key"] == "OTA"
    assert result["top_negative"][0]["contribution"] == 1.0
    assert result["top_positive"][0]["key"] == "协议"
    assert result["group_total_delta"] == -62_000.0


def test_rank_contributions_handles_zero_total():
    groups = [{"key": "A", "value": 10.0, "base": 10.0}]
    result = decompose.rank_contributions(groups, 0.0)
    assert result["rows"][0]["contribution"] is None


def test_deterministic_output():
    assert decompose.decompose(BASE, CURRENT) == decompose.decompose(BASE, CURRENT)
