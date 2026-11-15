"""角色 -> 权限点映射。README 与前端 site/js/config.js 同步。"""
from __future__ import annotations

from src.constants.enums import Role

ROLE_LABELS: dict[str, str] = {
    Role.ADMIN.value: "经营管理员",
    Role.ANALYST.value: "经营分析师",
    Role.VIEWER.value: "区域只读",
}

ROLE_DUTIES: dict[str, str] = {
    Role.ADMIN.value: "维护门店与指标口径、发起检测、出报告、看审计",
    Role.ANALYST.value: "发起检测、处理异常、写归因结论、导出明细",
    Role.VIEWER.value: "只读查看总览、异常与归因，不能写/导出/审计",
}

PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN.value: {
        "store:read", "store:write",
        "metric:read",
        "anomaly:read", "anomaly:review",
        "run:read", "run:create",
        "report:read", "report:generate",
        "calendar:read", "calendar:write",
        "export:read", "audit:read", "overview:read",
    },
    Role.ANALYST.value: {
        "store:read", "metric:read",
        "anomaly:read", "anomaly:review",
        "run:read", "run:create",
        "report:read", "export:read", "overview:read",
        "calendar:read",
    },
    Role.VIEWER.value: {
        "store:read", "metric:read", "anomaly:read", "run:read", "report:read", "overview:read",
        "calendar:read",
    },
}

STORE_WRITE_ROLES = (Role.ADMIN.value,)
RUN_CREATE_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
REVIEW_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
REPORT_GENERATE_ROLES = (Role.ADMIN.value,)
CALENDAR_WRITE_ROLES = (Role.ADMIN.value,)
EXPORT_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
AUDIT_ROLES = (Role.ADMIN.value,)
READ_ROLES = (Role.ADMIN.value, Role.ANALYST.value, Role.VIEWER.value)


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())
