"""经营报告（日报 / 周报），快照存 JSON，可导出 CSV。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(12), default="weekly")
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    generated_by: Mapped[str] = mapped_column(String(160), default="")
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    impact_total: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    calendar_version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    invalidated_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    invalidated_by_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
