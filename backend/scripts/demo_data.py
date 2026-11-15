"""演示数据集生成（纯计算、无数据库依赖；seed 与本地校验共用）。

规模：120 门店 × 90 天 × 3 渠道 = 32,400 条 MetricPoint（2026-08-16 ~ 2026-11-13）。
口径：渠道行 `revenue = adr × rooms_sold`；门店汇总 `revenue = adr × occ × rooms_available`
     （adr = Σrev/Σsold、occ = Σsold/rooms），恒等式在每条汇总行成立。
确定性：28 步整数周期 + 自研 LCG + 日期字符串哈希，不使用 random，两次构建逐字段一致。
"""
from __future__ import annotations

import math
from datetime import date, timedelta

START_DATE = date(2026, 8, 16)
DAYS = 90
STORE_COUNT = 120

CHANNELS: list[tuple[str, float, float]] = [
    ("ota", 0.55, 1.05),      # OTA：占比 55%，挂牌价系数 1.05
    ("direct", 0.30, 0.99),   # 直连/官网
    ("corp", 0.15, 0.90),     # 协议/团队
]

# 异常当日的渠道结构：模拟「OTA 侧限流」，OTA 占比临时下滑（用于让渠道归因可解释）
EVENT_CHANNELS: list[tuple[str, float, float]] = [
    ("ota", 0.532, 1.05),
    ("direct", 0.300, 0.99),
    ("corp", 0.168, 0.90),
]

REGIONS: list[tuple[str, str, list[str]]] = [
    ("HD", "华东", ["上海", "杭州", "南京", "苏州", "宁波"]),
    ("HN", "华南", ["深圳", "广州", "厦门", "珠海", "佛山"]),
    ("HB", "华北", ["北京", "天津", "青岛", "济南", "石家庄"]),
    ("XN", "西南", ["成都", "重庆", "昆明", "贵阳", "西安"]),
    ("HZ", "华中", ["武汉", "长沙", "郑州", "合肥", "南昌"]),
]

BRANDS = ["蓝湾精选", "蓝湾度假", "蓝湾轻居"]

# 28 步整数周期：任意 28 个连续工作日构成同一多重集 → 中位数 0、MAD=2 个单位，基线口径稳定
K_PATTERN = [-3, -2, -1, 1, 2, 3] * 4 + [-3, -2, 1, 2]

HEADLINE_STORE = "LB-HD-001"
HEADLINE_DATE = date(2026, 11, 3)
HEADLINE_IMPACT = -86_000.0
SHARES = {"adr": 0.62, "occ": 0.31, "rooms": 0.07}


def hash_code(text: str) -> int:
    total = 0
    for char in text:
        total = (total * 31 + ord(char)) % 1_000_003
    return total


def micro(seed: str, day: date) -> float:
    """[-1,1] 确定性微抖动，让日营收连续、MAD 可精确标定。"""
    return (hash_code(f"{seed}:{day.isoformat()}") % 2001 - 1000) / 1000.0


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def store_specs() -> list[dict]:
    specs: list[dict] = []
    for index in range(STORE_COUNT):
        region_code, region_name, cities = REGIONS[index % len(REGIONS)]
        city = cities[(index // len(REGIONS)) % len(cities)]
        if index == 0:
            specs.append(
                {
                    "code": HEADLINE_STORE,
                    "name": "蓝湾·外滩店",
                    "region": "华东",
                    "city": "上海",
                    "brand": "蓝湾精选",
                    "room_count": 240,
                    "manager": "顾青",
                    "status": "open",
                    "occ_base": 0.875,
                    "adr_base": 1702.67,
                    "vol_unit": 0.0180,
                    "micro_amp": 0.0100,
                }
            )
            continue
        specs.append(
            {
                "code": f"LB-{region_code}-{index // len(REGIONS) + 1:03d}",
                "name": f"蓝湾·{city}{['中心店', '新区店', '机场店', '会展店', '滨江店'][index % 5]}",
                "region": region_name,
                "city": city,
                "brand": BRANDS[index % len(BRANDS)],
                "room_count": 168 + (index % 13) * 12,
                "manager": f"店长{index:03d}",
                "status": "renovating" if index % 23 == 7 else "open",
                "occ_base": 0.70 + (index % 9) * 0.014,
                "adr_base": 1180.0 + (index % 11) * 32.0,
                "vol_unit": 0.0080 + (index % 6) * 0.0012,
            }
        )
    return specs


def room_mix(index: int) -> dict:
    return {
        "大床房": round(0.50 + (index % 3) * 0.02, 2),
        "双床房": round(0.36 - (index % 3) * 0.01, 2),
        "套房": round(0.14 - (index % 3) * 0.01, 2),
    }


def _days() -> list[date]:
    return [START_DATE + timedelta(days=offset) for offset in range(DAYS)]


def day_channels(
    spec: dict, day: date, sold: int, adr: float, rooms: int, index: int, channels: list[tuple[str, float, float]] | None = None
) -> list[dict]:
    """把门店当日售量与均价按渠道拆分（占比固定，均价按系数 + 微抖动浮动）。"""
    channels = channels or CHANNELS
    rows: list[dict] = []
    remaining = sold
    mix = room_mix(index)
    for position, (channel, share, multiplier) in enumerate(channels):
        if position == len(channels) - 1:
            channel_sold = remaining
        else:
            channel_sold = min(int(round(sold * share)), remaining)
        remaining -= channel_sold
        amplitude = spec.get("micro_amp", 0.0035)
        channel_adr = round(adr * multiplier * (1 + micro(f"{spec['code']}/{channel}", day) * amplitude), 2)
        rows.append(
            {
                "store_code": spec["code"],
                "stat_date": day,
                "channel": channel,
                "rooms_available": rooms,
                "rooms_sold": channel_sold,
                "occupancy": round(channel_sold / rooms, 6) if rooms else 0.0,
                "adr": channel_adr,
                "revenue": round(channel_adr * channel_sold, 2),
                "is_weekend": is_weekend(day),
                "room_type_mix": mix,
            }
        )
    return rows


def aggregate(day: date, channels: list[dict]) -> dict:
    rooms = max(row["rooms_available"] for row in channels)
    sold = sum(row["rooms_sold"] for row in channels)
    revenue = round(sum(row["revenue"] for row in channels), 2)
    return {
        "date": day,
        "rooms_available": rooms,
        "rooms_sold": sold,
        "occupancy": round(sold / rooms, 6) if rooms else 0.0,
        "adr": round(revenue / sold, 4) if sold else 0.0,
        "revenue": revenue,
        "is_weekend": is_weekend(day),
        "channels": channels,
    }


def build_series(spec: dict, overrides: dict[date, dict] | None = None) -> list[dict]:
    """构建门店 90 天序列；overrides 用于注入单日售量/均价/可售房量干预。"""
    overrides = overrides or {}
    rows: list[dict] = []
    weekday_counter = 0
    weekend_counter = 0
    phase = hash_code(spec["code"]) % 28
    vol = spec["vol_unit"] or 0.02
    for day in _days():
        weekend = is_weekend(day)
        if weekend:
            k = K_PATTERN[(weekend_counter + phase + 11) % 28]
            weekend_counter += 1
            factor = 1.075
        else:
            k = K_PATTERN[(weekday_counter + phase) % 28]
            weekday_counter += 1
            factor = 1.0
        rooms = spec["room_count"]
        sold = max(1, int(round(rooms * spec["occ_base"] * factor * (1 + k * vol))))
        adr = round(spec["adr_base"] * (1.05 if weekend else 1.0), 2)
        patch = overrides.get(day)
        channels = CHANNELS
        if patch:
            rooms = patch.get("rooms") or rooms
            sold = patch.get("sold") or sold
            adr = patch.get("adr") or adr
            channels = EVENT_CHANNELS if patch.get("mix") else CHANNELS
        rows.append(aggregate(day, day_channels(spec, day, sold, adr, rooms, 0, channels)))
    return rows


def median(values: list[float]) -> float:
    ordered = sorted(values)
    size = len(ordered)
    if size % 2:
        return ordered[size // 2]
    return (ordered[size // 2 - 1] + ordered[size // 2]) / 2


def window_stats(series: list[dict], index: int, window: int = 28) -> tuple[float, float, list[dict]]:
    """异常检测同口径：同周末分层、index 之前的最后 window 条。"""
    target = series[index]["is_weekend"]
    picked: list[dict] = []
    cursor = index - 1
    while cursor >= 0 and len(picked) < window:
        if series[cursor]["is_weekend"] != target:
            cursor -= 1
            continue
        picked.append(series[cursor])
        cursor -= 1
    picked.reverse()
    values = [row["revenue"] for row in picked]
    center = median(values)
    mad = median([abs(value - center) for value in values])
    return center, mad, picked


def base_triple(series: list[dict], index: int) -> tuple[float, float, dict]:
    center, mad, window = window_stats(series, index)
    base = {
        "adr": median([row["adr"] for row in window]),
        "occ": median([row["occupancy"] for row in window]),
        "rooms": median([float(row["rooms_available"]) for row in window]),
        "sold": median([float(row["rooms_sold"]) for row in window]),
        "revenue": center,
    }
    return center, mad, base


def _index_of(series: list[dict], day: date) -> int:
    return next(i for i, row in enumerate(series) if row["date"] == day)


def solve_headline(spec: dict) -> tuple[list[dict], dict]:
    """标定头条门店：稳健 z=-4.2、影响金额 -86,000 元、量价分摊 62/31/7。"""
    target_mad = abs(HEADLINE_IMPACT) * 0.6745 / 4.2
    dip_day = HEADLINE_DATE - timedelta(days=1)
    series: list[dict] = []
    overrides: dict[date, dict] = {}
    for _ in range(30):
        plain = build_series(spec)
        index = _index_of(plain, HEADLINE_DATE)
        _, mad_plain, _ = window_stats(plain, index)
        dip_units = 3.6 * mad_plain / 0.6745 / plain[_index_of(plain, dip_day)]["adr"]
        dip_sold = plain[_index_of(plain, dip_day)]["rooms_sold"] - dip_units
        overrides = {dip_day: {"sold": max(1, int(round(dip_sold)))}}
        series = build_series(spec, overrides)
        index = _index_of(series, HEADLINE_DATE)
        _, mad, _ = window_stats(series, index)
        if abs(mad - target_mad) < 9.0:
            break
        spec["vol_unit"] = spec["vol_unit"] * (target_mad / mad) if mad > 0 else spec["vol_unit"]
    index = _index_of(series, HEADLINE_DATE)
    center, mad, base = base_triple(series, index)
    drop = solve_event(spec, series, index, 4.2)
    overrides[HEADLINE_DATE] = drop["triple"]
    series = build_series(spec, overrides)
    row = series[index]
    return series, {
        "center": center,
        "mad": mad,
        "base": base,
        "robust_z": drop["robust_z"],
        "impact_amount": round(row["revenue"] - center, 2),
        "overrides": overrides,
    }


def _construct(spec: dict, base: dict, day: date, ratio: float, shares: dict) -> dict:
    log_ratio = math.log(ratio)
    rooms = max(20, int(round(base["rooms"] * math.exp(shares["rooms"] * log_ratio))))
    sold = max(5, int(round(rooms * base["occ"] * math.exp(shares["occ"] * log_ratio))))
    adr = round(base["adr"] * math.exp(shares["adr"] * log_ratio), 2)
    revenue = round(sum(row["revenue"] for row in day_channels(spec, day, sold, adr, rooms, 0, EVENT_CHANNELS)), 2)
    return {"rooms": rooms, "sold": sold, "adr": adr, "revenue": revenue}


def _tune_ratio(spec: dict, base: dict, day: date, target_revenue: float, shares: dict) -> dict:
    """对 ratio 做二分：营收对 ratio 单调，二分 70 次可稳定收敛到 10 元以内。"""
    low, high = 0.20, 1.05
    best = _construct(spec, base, day, high, shares)
    for _ in range(70):
        mid = (low + high) / 2
        candidate = _construct(spec, base, day, mid, shares)
        if abs(candidate["revenue"] - target_revenue) < abs(best["revenue"] - target_revenue):
            best = candidate
        if abs(candidate["revenue"] - target_revenue) < 8:
            return candidate
        if candidate["revenue"] < target_revenue:
            low = mid
        else:
            high = mid
    # 末段用均价做精细收敛（营收对 adr 是连续可调，最小步长 ≈ 售出房晚 × 0.01 元）
    for _ in range(6):
        gap = target_revenue - best["revenue"]
        if abs(gap) < 6:
            break
        adr = round(best["adr"] + gap / max(1, best["sold"]), 2)
        revenue = round(
            sum(
                row["revenue"]
                for row in day_channels(spec, day, best["sold"], adr, best["rooms"], 0, EVENT_CHANNELS)
            ),
            2,
        )
        best = {"rooms": best["rooms"], "sold": best["sold"], "adr": adr, "revenue": revenue}
    return best


def solve_event(spec: dict, series: list[dict], index: int, target_z: float, shares: dict | None = None) -> dict:
    """在 index 处造一次「量价分摊」下跌：收敛到目标稳健 z，并把三项占比校准到 62/31/7。"""
    shares = dict(shares or SHARES)
    center, mad, base = base_triple(series, index)
    target_revenue = center - abs(target_z) * mad / 0.6745
    day = series[index]["date"]
    best = _tune_ratio(spec, base, day, target_revenue, shares)
    for _ in range(14):
        agg = aggregate(day, day_channels(spec, day, best["sold"], best["adr"], best["rooms"], 0, EVENT_CHANNELS))
        current = {"adr": agg["adr"], "occ": agg["occupancy"], "rooms": float(agg["rooms_available"]), "revenue": agg["revenue"]}
        parts = _lodi_shares(base, current)
        if parts is None:
            break
        drift = max(abs(parts[key] - SHARES[key]) for key in SHARES)
        if drift < 0.002:
            break
        for key in ("adr", "occ", "rooms"):
            shares[key] = max(0.01, shares[key] + (SHARES[key] - parts[key]) * 0.6)
        total = sum(shares.values())
        shares = {key: value / total for key, value in shares.items()}
        best = _tune_ratio(spec, base, day, target_revenue, shares)
    z = 0.6745 * (best["revenue"] - center) / mad
    best = {**best, "mix": True}
    return {"triple": best, "robust_z": round(z, 4), "center": center, "mad": mad, "target_revenue": round(target_revenue, 2), "shares": shares}


def _lodi_shares(base: dict, current: dict) -> dict | None:
    a, b = base["adr"], current["adr"]
    o, p = base["occ"], current["occ"]
    r, s = base["rooms"], current["rooms"]
    rb, rc = base["revenue"], current["revenue"]
    if min(a, b, o, p, r, s, rb, rc) <= 0 or abs(rc - rb) < 1e-6:
        return None
    total = rc - rb
    weight = (rc - rb) / (math.log(rc) - math.log(rb))
    parts = {
        "adr": weight * math.log(b / a),
        "occ": weight * math.log(p / o),
        "rooms": weight * math.log(s / r),
    }
    return {key: value / total for key, value in parts.items()}


# ---- 异常事件计划：37 起（1 起头条 + 36 起）----
def _weekday_dates(count: int) -> list[date]:
    out: list[date] = []
    cursor = date(2026, 9, 24)
    while len(out) < count:
        if not is_weekend(cursor):
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


EVENT_DATES = _weekday_dates(36)
_Z_HIGH = [5.9, 5.5, 5.2, 5.6, 5.4, 5.1, 5.7, 5.3]
_Z_MEDIUM = [4.4, 4.6, 4.2, 4.8, 4.5, 4.3, 4.7, 4.2, 4.9, 4.3, 4.6, 4.4, 4.5, 4.2, 4.3]
_Z_LOW = [4.0, 4.1, 3.9, 4.0, 4.1, 3.9, 4.0, 3.9, 4.0, 4.1, 3.9, 4.0, 3.9]


def event_plan() -> list[tuple[int, date, float]]:
    zs = _Z_HIGH + _Z_MEDIUM + _Z_LOW
    return [(position + 1, EVENT_DATES[position], zs[position]) for position in range(36)]


def build_dataset() -> dict:
    specs = store_specs()
    plan = event_plan()
    dips: dict[str, list[tuple[date, float]]] = {}
    for store_index, event_date, target_z in plan:
        dips.setdefault(specs[store_index]["code"], []).append((event_date, target_z))

    events: list[dict] = []
    headline_series, headline_stats = solve_headline(specs[0])
    for day, patch in headline_stats["overrides"].items():
        pass
    events.append(
        {
            "store_code": specs[0]["code"],
            "store_index": 0,
            "metric_date": HEADLINE_DATE.isoformat(),
            "target_z": -4.2,
            "robust_z": headline_stats["robust_z"],
            "impact_amount": headline_stats["impact_amount"],
            "center": headline_stats["center"],
            "mad": headline_stats["mad"],
            "headline": True,
        }
    )

    series_by_code: dict[str, list[dict]] = {specs[0]["code"]: headline_series}
    for index, spec in enumerate(specs[1:], start=1):
        overrides: dict[date, dict] = {}
        series = build_series(spec)
        planned = dips.get(spec["code"], [])
        for event_date, _ in planned:
            dip_day = event_date - timedelta(days=1)
            dip_index = _index_of(series, dip_day)
            _, mad_plain, _ = window_stats(series, dip_index)
            units = 3.6 * mad_plain / 0.6745 / series[dip_index]["adr"]
            overrides[dip_day] = {"sold": max(1, int(round(series[dip_index]["rooms_sold"] - units)))}
            series = build_series(spec, overrides)
        for event_date, target_z in planned:
            index_in_series = _index_of(series, event_date)
            drop = solve_event(spec, series, index_in_series, target_z)
            overrides[event_date] = drop["triple"]
            series = build_series(spec, overrides)
            events.append(
                {
                    "store_code": spec["code"],
                    "store_index": index,
                    "metric_date": event_date.isoformat(),
                    "target_z": -target_z,
                    "robust_z": drop["robust_z"],
                    "impact_amount": round(series[index_in_series]["revenue"] - drop["center"], 2),
                    "center": drop["center"],
                    "mad": drop["mad"],
                    "headline": False,
                }
            )
        series_by_code[spec["code"]] = series

    points: list[dict] = []
    for index, spec in enumerate(specs):
        for row in series_by_code[spec["code"]]:
            for channel_row in row["channels"]:
                channel_row["room_type_mix"] = room_mix(index)
                points.append(channel_row)

    events.sort(key=lambda item: (not item["headline"], item["metric_date"], item["store_code"]))
    return {
        "stores": specs,
        "points": points,
        "events": events,
        "headline": events[0],
        "meta": {
            "stores": len(specs),
            "days": DAYS,
            "channels": len(CHANNELS),
            "points": len(points),
            "events": len(events),
        },
    }


if __name__ == "__main__":  # 本地校验入口：python -m scripts.demo_data
    import json

    dataset = build_dataset()
    print(json.dumps(dataset["meta"], ensure_ascii=False))
    print(json.dumps(dataset["headline"], ensure_ascii=False, default=str))
