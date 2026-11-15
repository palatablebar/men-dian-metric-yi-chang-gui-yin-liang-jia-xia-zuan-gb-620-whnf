"""算法 B｜营收变动的 LMDI 量价分解 + 维度贡献下钻。

口径（README §10 同步）：
- 营收恒等式：`revenue = adr × occupancy × rooms_available`（已售房晚 = occupancy × 可售房量）；
- 变动：`Δrev = rev_cur - rev_base`；
- 对数平均分解（LMDI-I 加法形式）：
  `L = Δrev / (ln rev_cur - ln rev_base)`（对数平均，rev_cur == rev_base 时取 rev_base），
  `part_adr = L × ln(adr_cur / adr_base)`，occ / rooms 同理；
  三项之和与 Δrev 的差额（浮点残差）写入 `residual`，不摊派、不隐藏；
- 占比：`share_i = part_i / Δrev`（Δrev 为 0 时全部写 null，避免除零）；
- 维度贡献：`contribution_g = Δ_g / ΣΔ_g`，按 |Δ| 排序输出 top3 正 / 负贡献；
- 边界：任一因子 ≤ 0 或 rev ≤ 0 时对数无定义 → `status="degenerate"`，不产出占比，只回原始三元组；
- 纯函数、无外部依赖、确定性（同输入同输出）。
"""
from __future__ import annotations

import math

METHOD = "LMDI-I additive (log-mean weights)"
EPS = 1e-9


def _log_mean(a: float, b: float) -> float:
    if abs(a - b) <= EPS:
        return a
    if a <= 0 or b <= 0:
        raise ValueError("log mean undefined for non-positive revenue")
    return (a - b) / (math.log(a) - math.log(b))


def decompose(base: dict, current: dict) -> dict:
    """base / current 各需含 adr、occ、rooms、revenue。"""
    base_adr, base_occ, base_rooms = float(base["adr"]), float(base["occ"]), float(base["rooms"])
    cur_adr, cur_occ, cur_rooms = float(current["adr"]), float(current["occ"]), float(current["rooms"])
    base_rev = float(base["revenue"])
    cur_rev = float(current["revenue"])
    total = cur_rev - base_rev

    triple_base = {"adr": round(base_adr, 4), "occ": round(base_occ, 6), "rooms": round(base_rooms, 2), "revenue": round(base_rev, 2)}
    triple_cur = {"adr": round(cur_adr, 4), "occ": round(cur_occ, 6), "rooms": round(cur_rooms, 2), "revenue": round(cur_rev, 2)}

    if min(base_adr, base_occ, base_rooms, cur_adr, cur_occ, cur_rooms, base_rev, cur_rev) <= 0:
        return {
            "status": "degenerate",
            "method": METHOD,
            "reason": "非正因子无法取对数",
            "total_delta": round(total, 2),
            "parts": {"adr": None, "occ": None, "rooms": None},
            "shares": {"adr": None, "occ": None, "rooms": None},
            "residual": None,
            "base": triple_base,
            "current": triple_cur,
        }

    if abs(total) <= EPS:
        return {
            "status": "flat",
            "method": METHOD,
            "reason": "营收与基线一致，无可分解变动",
            "total_delta": 0.0,
            "parts": {"adr": 0.0, "occ": 0.0, "rooms": 0.0},
            "shares": {"adr": None, "occ": None, "rooms": None},
            "residual": 0.0,
            "base": triple_base,
            "current": triple_cur,
        }

    weight = _log_mean(cur_rev, base_rev)
    part_adr = weight * math.log(cur_adr / base_adr)
    part_occ = weight * math.log(cur_occ / base_occ)
    part_rooms = weight * math.log(cur_rooms / base_rooms)
    parts = {"adr": part_adr, "occ": part_occ, "rooms": part_rooms}
    residual = total - (part_adr + part_occ + part_rooms)
    shares = {key: value / total for key, value in parts.items()}
    return {
        "status": "ok",
        "method": METHOD,
        "reason": "",
        "total_delta": round(total, 2),
        "parts": {key: round(value, 2) for key, value in parts.items()},
        "shares": {key: round(value, 6) for key, value in shares.items()},
        "residual": round(residual, 6),
        "base": triple_base,
        "current": triple_cur,
        "log_mean_weight": round(weight, 4),
    }


def rank_contributions(groups: list[dict], total_delta: float, top: int = 3) -> dict:
    """groups: [{"key": 显示名, "value": 当期值, "base": 基期值}]。"""
    rows = []
    for group in groups:
        delta = float(group["value"]) - float(group["base"])
        share = None if abs(total_delta) <= EPS else delta / total_delta
        rows.append(
            {
                "key": str(group["key"]),
                "current": round(float(group["value"]), 2),
                "base": round(float(group["base"]), 2),
                "delta": round(delta, 2),
                "contribution": None if share is None else round(share, 6),
            }
        )
    rows.sort(key=lambda item: (-abs(item["delta"]), item["key"]))
    negatives = sorted([row for row in rows if row["delta"] < 0], key=lambda item: (item["delta"], item["key"]))[:top]
    positives = sorted([row for row in rows if row["delta"] > 0], key=lambda item: (-item["delta"], item["key"]))[:top]
    return {
        "rows": rows,
        "top_negative": negatives,
        "top_positive": positives,
        "group_total_delta": round(sum(row["delta"] for row in rows), 2),
    }


def narrative(result: dict, dimension_rows: list[dict], store_name: str, metric_date: str) -> str:
    """生成中文解释文本（写入归因结论，导出与页面共用）。占比 = 该因子变动 / 总变动。"""
    labels = {"adr": "房价(ADR)", "occ": "出租率(OCC)", "rooms": "可售房量(ROOMS)"}
    if result["status"] != "ok":
        return f"{store_name} {metric_date} 变动过小或因子非正，无法做量价分解（{result['reason']}）。"
    total = result["total_delta"]
    parts = result["parts"]
    shares = result["shares"]
    ordered = sorted(shares.items(), key=lambda item: -abs(item[1] or 0))
    driver = ordered[0][0]
    head = f"{store_name} {metric_date} 营收 {total:+,.0f} 元，主因{labels[driver]}（占变动 {shares[driver] * 100:+.1f}%）"
    if dimension_rows:
        top = dimension_rows[0]
        if top.get("contribution") is not None:
            head += f"；维度上「{top['key']}」贡献 {top['contribution'] * 100:+.1f}%（{top['delta']:+,.0f} 元）"
    breakdown = "，".join(f"{labels[key]} {parts[key]:+,.0f} 元（占 {shares[key] * 100:.1f}%）" for key in ("adr", "occ", "rooms"))
    return f"{head}。量价拆解：{breakdown}；残差 {result['residual']:+.4f} 元（对数平均权重的浮点残差，不摊派）。"
