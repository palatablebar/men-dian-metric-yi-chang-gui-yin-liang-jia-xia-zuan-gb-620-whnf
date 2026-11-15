"""归因（与异常一对一）：LMDI 量价分解 + 三维贡献 + 结论文本。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class Attribution(Base):
    __tablename__ = "attributions"
    __table_args__ = (UniqueConstraint("anomaly_id", name="uq_attribution_anomaly"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id", ondelete="CASCADE"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    base_rev: Mapped[float] = mapped_column(Float, default=0.0)
    cur_rev: Mapped[float] = mapped_column(Float, default=0.0)
    total_delta: Mapped[float] = mapped_column(Float, default=0.0)
    adr_part: Mapped[float] = mapped_column(Float, default=0.0)
    occ_part: Mapped[float] = mapped_column(Float, default=0.0)
    rooms_part: Mapped[float] = mapped_column(Float, default=0.0)
    adr_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    occ_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    rooms_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual: Mapped[float] = mapped_column(Float, default=0.0)
    drivers: Mapped[dict] = mapped_column(JSON, default=dict)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[str] = mapped_column(Text, default="")
    calendar_version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    sample_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
