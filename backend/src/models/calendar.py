"""运营日历：门店 × 生效日期区间 × 特殊日类型，以及日历规则变更版本。

口径：
- 一条记录表示某门店在 `[start_date, end_date]`（含端点）生效的一类特殊运营日；
- 特殊日类型 `promo`（大促日）/ `renovating`（停业改造）/ `closed`（临时闭店）
  统一**不进入常态基线**；
- 每次新增 / 修改 / 停用规则都会产生一条 `CalendarRevision`，全局 `version` 单调递增；
- 异常、报告都记录生成时的 `calendar_version`，用于失效重算与“已发布报告保留原引用”。
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class OperatingCalendar(Base):
    __tablename__ = "operating_calendar"
    __table_args__ = (
        UniqueConstraint("store_id", "day_type", "start_date", "end_date", name="uq_calendar_store_type_span"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    day_type: Mapped[str] = mapped_column(String(20), index=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    label: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    calendar_version: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(160), default="")
    seed_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CalendarRevision(Base):
    __tablename__ = "calendar_revisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    action: Mapped[str] = mapped_column(String(20), default="create")
    actor_email: Mapped[str] = mapped_column(String(160), default="")
    summary: Mapped[str] = mapped_column(String(200), default="")
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    seed_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
