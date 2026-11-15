"""算法 A｜门店指标稳健异常检测（滚动中位数 + MAD，周末分层，方向延续）。

口径（README §10 同步，改动需两侧一致）：
- 基线窗口：取当前点之前、**同一周末/工作日分层**的最后 `window`(默认 28) 个观测；
- 稳健统计量：`median` 与 `MAD = median(|x - median|)`；`MAD == 0` 时退化为平均绝对偏差，
  仍为 0 则视为「基线无波动」，记入 skipped，不产出异常；
- 稳健 z：`robust_z = 0.6745 * (x - median) / MAD`（0.6745 为正态下 MAD 与 σ 的比例常数）；
- 触发条件：`|z| >= threshold`(默认 3.5) **且** 前一观测同方向且 `|z_prev| >= persist_z`(默认 1.5)，
  即「方向一致 2 天」，避免单日抖动误报；
- 严重度：`|z| >= 5.0 或 |影响金额| >= 80000` → high；`|z| >= 4.2 或 >= 30000` → medium；否则 low；
- 影响金额（按指标）：rev → `Δ营收`；adr → `Δadr × 当期已售房晚`；occ → `Δocc × 当期可售房量 × 当期adr`；
- 纯函数、无数据库与框架依赖，同一输入两次输出逐字段一致（可单测）。
"""
from __future__ import annotations

from statistics import median

MAD_SCALE = 0.6745

DEFAULTS: dict[str, float | int | bool] = {
    "window": 28,
    "threshold": 3.5,
    "persist_z": 1.5,
    "min_samples": 10,
    "stratify": True,
}

SEVERITY_HIGH_Z = 5.0
SEVERITY_MEDIUM_Z = 4.2
SEVERITY_HIGH_AMOUNT = 80_000.0
SEVERITY_MEDIUM_AMOUNT = 30_000.0

METRIC_KEYS = ("rev", "adr", "occ")


def robust_stats(values: list[float]) -> tuple[float, float, str]:
    """返回 (median, MAD, mad_basis)。mad_basis 记录是否退化。"""
    if not values:
        raise ValueError("robust_stats requires at least one value")
    center = median(values)
    deviations = [abs(value - center) for value in values]
    mad = median(deviations)
    basis = "mad"
    if mad <= 0:
        mad = sum(deviations) / len(deviations)
        basis = "mean-abs-dev"
    if mad <= 0:
        basis = "degenerate"
    return float(center), float(mad), basis


def trailing_window(series: list[dict], index: int, window: int, stratify: bool) -> list[dict]:
    """index 之前、可选按周末分层、最多 window 条，保持时间升序。"""
    target_weekend = bool(series[index]["is_weekend"])
    picked: list[dict] = []
    cursor = index - 1
    while cursor >= 0 and len(picked) < window:
        row = series[cursor]
        if stratify and bool(row["is_weekend"]) != target_weekend:
            cursor -= 1
            continue
        picked.append(row)
        cursor -= 1
    picked.reverse()
    return picked


def _baseline_triple(window: list[dict]) -> dict:
    return {
        "adr": float(median([row["adr"] for row in window])),
        "occ": float(median([row["occupancy"] for row in window])),
        "rooms": float(median([row["rooms_available"] for row in window])),
        "sold": float(median([row["rooms_sold"] for row in window])),
        "revenue": float(median([row["revenue"] for row in window])),
    }


def impact_of(metric_key: str, current: dict, baseline: dict) -> float:
    if metric_key == "rev":
        return float(current["revenue"] - baseline["revenue"])
    if metric_key == "adr":
        return float((current["adr"] - baseline["adr"]) * current["rooms_sold"])
    if metric_key == "occ":
        return float((current["occupancy"] - baseline["occ"]) * current["rooms_available"] * current["adr"])
    raise ValueError(f"unsupported metric: {metric_key}")


def severity_of(robust_z: float, impact: float) -> str:
    absolute_z = abs(robust_z)
    absolute_amount = abs(impact)
    if absolute_z >= SEVERITY_HIGH_Z or absolute_amount >= SEVERITY_HIGH_AMOUNT:
        return "high"
    if absolute_z >= SEVERITY_MEDIUM_Z or absolute_amount >= SEVERITY_MEDIUM_AMOUNT:
        return "medium"
    return "low"


def _value_of(row: dict, metric_key: str) -> float:
    if metric_key == "rev":
        return float(row["revenue"])
    if metric_key == "adr":
        return float(row["adr"])
    if metric_key == "occ":
        return float(row["occupancy"])
    raise ValueError(f"unsupported metric: {metric_key}")


def detect_series(series: list[dict], metric_key: str = "rev", **options) -> dict:
    """对一条时间升序的门店序列做异常检测。

    series 元素需含：date(iso str)、revenue、adr、occupancy、rooms_available、rooms_sold、is_weekend。
    返回 {"hits": [...], "skipped": [...], "evaluated": n, "params": {...}}。
    """
    params = {**DEFAULTS, **{key: value for key, value in options.items() if key in DEFAULTS}}
    window_size = int(params["window"])
    threshold = float(params["threshold"])
    persist_z = float(params["persist_z"])
    min_samples = int(params["min_samples"])
    stratify = bool(params["stratify"])

    hits: list[dict] = []
    skipped: list[dict] = []
    z_cache: dict[int, float] = {}
    evaluated = 0

    for index in range(len(series)):
        window = trailing_window(series, index, window_size, stratify)
        if len(window) < min_samples:
            skipped.append({"date": series[index]["date"], "reason": "insufficient_baseline", "samples": len(window)})
            continue
        values = [_value_of(row, metric_key) for row in window]
        center, mad, basis = robust_stats(values)
        current = series[index]
        raw = _value_of(current, metric_key)
        if basis == "degenerate":
            skipped.append({"date": current["date"], "reason": "degenerate_baseline", "samples": len(window)})
            continue
        evaluated += 1
        robust_z = MAD_SCALE * (raw - center) / mad
        z_cache[index] = robust_z
        if abs(robust_z) < threshold:
            continue
        direction = "down" if robust_z < 0 else "up"

        previous_ok = False
        previous_z = None
        if index >= 1:
            prev_index = index - 1
            if prev_index not in z_cache:
                prev_window = trailing_window(series, prev_index, window_size, stratify)
                if len(prev_window) >= min_samples:
                    prev_values = [_value_of(row, metric_key) for row in prev_window]
                    prev_center, prev_mad, prev_basis = robust_stats(prev_values)
                    if prev_basis != "degenerate":
                        prev_raw = _value_of(series[prev_index], metric_key)
                        z_cache[prev_index] = MAD_SCALE * (prev_raw - prev_center) / prev_mad
            previous_z = z_cache.get(prev_index)
            if previous_z is not None:
                same_direction = (previous_z < 0) == (robust_z < 0)
                previous_ok = same_direction and abs(previous_z) >= persist_z
        if not previous_ok:
            skipped.append(
                {
                    "date": current["date"],
                    "reason": "no_direction_persist",
                    "robust_z": round(robust_z, 4),
                    "previous_z": None if previous_z is None else round(previous_z, 4),
                }
            )
            continue

        baseline = _baseline_triple(window)
        impact = impact_of(metric_key, current, baseline)
        hits.append(
            {
                "date": current["date"],
                "metric_key": metric_key,
                "observed": round(raw, 6),
                "baseline": round(center, 6),
                "mad": round(mad, 6),
                "robust_z": round(robust_z, 4),
                "direction": direction,
                "impact_amount": round(impact, 2),
                "severity": severity_of(robust_z, impact),
                "mad_basis": basis,
                "window_samples": len(window),
                "window_start": window[0]["date"],
                "window_end": window[-1]["date"],
                "baseline_triple": {key: round(value, 6) for key, value in baseline.items()},
                "current_triple": {
                    "adr": round(float(current["adr"]), 6),
                    "occ": round(float(current["occupancy"]), 6),
                    "rooms": float(current["rooms_available"]),
                    "sold": float(current["rooms_sold"]),
                    "revenue": round(float(current["revenue"]), 6),
                },
            }
        )

    hits.sort(key=lambda item: (-abs(item["robust_z"]), item["date"]))
    return {
        "hits": hits,
        "skipped": skipped,
        "evaluated": evaluated,
        "params": {
            "metric_key": metric_key,
            "window": window_size,
            "threshold": threshold,
            "persist_z": persist_z,
            "min_samples": min_samples,
            "stratify": stratify,
            "mad_scale": MAD_SCALE,
        },
    }
