"""失效重算任务执行记录：日历变更后受影响异常与草稿报告的恢复与续跑。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_no: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="recompute", index=True)
    calendar_version: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    stage: Mapped[str] = mapped_column(String(20), default="staged")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    staging: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    recovered_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotent_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    log_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
