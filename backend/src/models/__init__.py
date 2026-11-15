"""ORM 模型聚合导出（Base 用于 create_all）。"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from src.models.user import User  # noqa: E402
from src.models.audit import AuditLog  # noqa: E402
from src.models.store import Store  # noqa: E402
from src.models.metric import MetricPoint  # noqa: E402
from src.models.run import Run  # noqa: E402
from src.models.anomaly import Anomaly  # noqa: E402
from src.models.attribution import Attribution  # noqa: E402
from src.models.report import Report  # noqa: E402

__all__ = [
    "Base",
    "User",
    "AuditLog",
    "Store",
    "MetricPoint",
    "Run",
    "Anomaly",
    "Attribution",
    "Report",
]
