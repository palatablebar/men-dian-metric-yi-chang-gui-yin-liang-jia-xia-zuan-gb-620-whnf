from __future__ import annotations

from pydantic import BaseModel, Field


class ReportIn(BaseModel):
    kind: str = Field(default="weekly", pattern=r"^(daily|weekly)$")
    period_start: str | None = None
    period_end: str | None = None
    note: str | None = Field(default=None, max_length=500)


class ReportPatch(BaseModel):
    status: str = Field(pattern=r"^(draft|published)$")
    note: str | None = Field(default=None, max_length=500)
