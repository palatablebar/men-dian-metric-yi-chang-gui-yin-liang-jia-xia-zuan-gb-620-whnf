"""演示账号与种子口径（seed 与文档的唯一数值来源）。"""

DEMO_PASSWORD = "Demo@2026"

DEMO_USERS = [
    ("admin@anomalyattr.io", "林可 · 经营管理员", "admin"),
    ("analyst@anomalyattr.io", "周棠 · 经营分析师", "analyst"),
    ("viewer@anomalyattr.io", "陈默 · 区域只读", "viewer"),
]

ORG = "蓝湾酒店集团 · 经营分析组"

# 检测运行口径（与 README §10、前端展示一致）
SEED_RUN = {
    "seed_key": "seed-run-detect-1",
    "trigger": "seed",
    "operator": "analyst@anomalyattr.io",
    "params": {"metrics": ["rev"], "window": 28, "threshold": 3.5, "persist_z": 1.5, "stratify": True},
}

SEED_REPORT = {
    "seed_key": "seed-report-weekly-1",
    "kind": "weekly",
    "period_start": "2026-10-26",
    "period_end": "2026-11-01",
    "title": "蓝湾酒店集团 2026-10-26 ~ 2026-11-01 经营异常周报",
    "status": "published",
}

# seed 预置的处理结论（不覆盖人工后续修改）
SEED_REVIEWS = [
    ("LB-HN-001", "2026-09-24", "confirmed", "OTA 侧限流导致当日曝光骤降，已要求渠道经理补量。"),
    ("LB-HB-001", "2026-09-25", "confirmed", "当地区域展会取消，需求侧下滑，非门店经营问题。"),
    ("LB-HD-002", "2026-09-30", "dismissed", "PMS 上报延迟导致的补传，核对后为口径缺失，已重跑。"),
]

# 运营日历种子（按门店 + 生效区间；均为「不进入常态基线」的特殊日）
# 这些规则刻意避开了 37 起预置异常的发生日，只改变可比样本与 z 值，不改变异常起数。
SEED_CALENDAR = [
    {
        "seed_key": "seed-calendar-renov-1",
        "store_code": "LB-HB-002",
        "day_type": "renovating",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "label": "华北 · 客房层改造",
        "note": "改造期间仅保留半数客房，营收与出租率不可比，不纳入基线。",
    },
    {
        "seed_key": "seed-calendar-renov-2",
        "store_code": "LB-HD-007",
        "day_type": "renovating",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "label": "华东 · 大堂与早餐厅改造",
        "note": "OTA 房量临时下降，属特殊运营日。",
    },
    {
        "seed_key": "seed-calendar-closed-1",
        "store_code": "LB-XN-011",
        "day_type": "closed",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "label": "西南 · 设备检修临时闭店",
        "note": "闭店期间无正常经营，不纳入可比样本。",
    },
    {
        "seed_key": "seed-calendar-renov-3",
        "store_code": "LB-HN-016",
        "day_type": "renovating",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "label": "华南 · 客房软装升级",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-renov-4",
        "store_code": "LB-HZ-020",
        "day_type": "renovating",
        "start_date": "2026-09-01",
        "end_date": "2026-09-14",
        "label": "华中 · 楼层改造",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-promo-1",
        "store_code": "LB-HB-002",
        "day_type": "promo",
        "start_date": "2026-10-17",
        "end_date": "2026-10-18",
        "label": "秋季大促",
        "note": "大促价与常态价不可比，不进基线；当期结果仍按真实成交价说明。",
    },
    {
        "seed_key": "seed-calendar-promo-2",
        "store_code": "LB-HD-007",
        "day_type": "promo",
        "start_date": "2026-10-17",
        "end_date": "2026-10-18",
        "label": "秋季大促",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-promo-3",
        "store_code": "LB-XN-011",
        "day_type": "promo",
        "start_date": "2026-10-17",
        "end_date": "2026-10-18",
        "label": "秋季大促",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-promo-4",
        "store_code": "LB-HN-016",
        "day_type": "promo",
        "start_date": "2026-10-17",
        "end_date": "2026-10-18",
        "label": "秋季大促",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-promo-5",
        "store_code": "LB-HZ-020",
        "day_type": "promo",
        "start_date": "2026-10-17",
        "end_date": "2026-10-18",
        "label": "秋季大促",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-promo-11",
        "store_code": "LB-HD-007",
        "day_type": "promo",
        "start_date": "2026-11-11",
        "end_date": "2026-11-11",
        "label": "双十一大促",
        "note": "",
    },
    {
        "seed_key": "seed-calendar-promo-12",
        "store_code": "LB-HN-016",
        "day_type": "promo",
        "start_date": "2026-11-11",
        "end_date": "2026-11-11",
        "label": "双十一大促",
        "note": "",
    },
]
