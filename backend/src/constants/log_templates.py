"""审计动作 -> 中文标签。"""
from __future__ import annotations

ACTIONS: dict[str, str] = {
    "auth.login": "登录",
    "store.create": "新建门店",
    "store.update": "修改门店",
    "run.create": "发起异常检测",
    "run.complete": "检测完成",
    "anomaly.review": "处理异常",
    "attribution.build": "生成归因",
    "report.generate": "生成报告",
    "report.publish": "发布报告",
    "export.anomalies": "导出异常清单",
    "export.attributions": "导出归因明细",
    "export.report": "导出报告",
    "http.mutation": "写请求",
}
