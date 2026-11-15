"""共享枚举（后端唯一定义处）。前端副本见 frontend/site/js/config.js。

README「共享枚举出现位置」列出全部出现点，改动需两侧同步。
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Channel(StrEnum):
    """经营渠道。MetricPoint 的自然键之一。"""

    OTA = "ota"
    DIRECT = "direct"
    CORP = "corp"


CHANNEL_LABELS: dict[str, str] = {
    Channel.OTA.value: "OTA 渠道",
    Channel.DIRECT.value: "直连/官网",
    Channel.CORP.value: "协议/团队",
}

CHANNEL_ORDER: list[str] = [Channel.OTA.value, Channel.DIRECT.value, Channel.CORP.value]


class MetricKey(StrEnum):
    """可检测/可分解的指标。"""

    REV = "rev"
    ADR = "adr"
    OCC = "occ"


METRIC_LABELS: dict[str, str] = {
    MetricKey.REV.value: "营收",
    MetricKey.ADR.value: "平均房价 ADR",
    MetricKey.OCC.value: "出租率 OCC",
}

METRIC_UNITS: dict[str, str] = {
    MetricKey.REV.value: "元",
    MetricKey.ADR.value: "元/间夜",
    MetricKey.OCC.value: "%",
}

METRIC_ORDER: list[str] = [MetricKey.REV.value, MetricKey.ADR.value, MetricKey.OCC.value]


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"


DIRECTION_LABELS: dict[str, str] = {Direction.UP.value: "上行", Direction.DOWN.value: "下行"}


class StoreStatus(StrEnum):
    OPEN = "open"
    RENOVATING = "renovating"
    CLOSED = "closed"


STORE_STATUS_LABELS: dict[str, str] = {
    StoreStatus.OPEN.value: "营业中",
    StoreStatus.RENOVATING.value: "局部改造",
    StoreStatus.CLOSED.value: "暂停营业",
}


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


RUN_STATUS_LABELS: dict[str, str] = {
    RunStatus.QUEUED.value: "排队中",
    RunStatus.RUNNING.value: "执行中",
    RunStatus.SUCCESS.value: "成功",
    RunStatus.PARTIAL.value: "部分成功",
    RunStatus.FAILED.value: "失败",
}


class TriggerKind(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    SEED = "seed"


TRIGGER_LABELS: dict[str, str] = {
    TriggerKind.MANUAL.value: "手动",
    TriggerKind.SCHEDULE.value: "定时",
    TriggerKind.SEED.value: "初始化",
}


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_LABELS: dict[str, str] = {Severity.HIGH.value: "高", Severity.MEDIUM.value: "中", Severity.LOW.value: "低"}

SEVERITY_ORDER: list[str] = [Severity.HIGH.value, Severity.MEDIUM.value, Severity.LOW.value]


class ReviewStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


REVIEW_STATUS_LABELS: dict[str, str] = {
    ReviewStatus.PENDING.value: "待处理",
    ReviewStatus.CONFIRMED.value: "已确认",
    ReviewStatus.DISMISSED.value: "已排除",
}

REVIEW_STATUS_ORDER: list[str] = [
    ReviewStatus.PENDING.value,
    ReviewStatus.CONFIRMED.value,
    ReviewStatus.DISMISSED.value,
]


class ReportKind(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


REPORT_KIND_LABELS: dict[str, str] = {ReportKind.DAILY.value: "日报", ReportKind.WEEKLY.value: "周报"}


class ReportStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


REPORT_STATUS_LABELS: dict[str, str] = {ReportStatus.DRAFT.value: "草稿", ReportStatus.PUBLISHED.value: "已发布"}


# 算法 A 默认参数（detection.DEFAULTS 的对外镜像，前端只展示不计算）
DETECTION_DEFAULTS: dict[str, float | int | bool] = {
    "window": 28,
    "threshold": 3.5,
    "persist_z": 1.5,
    "min_samples": 10,
    "mad_scale": 0.6745,
    "stratify": "weekend",
}
