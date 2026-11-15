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
