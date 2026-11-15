from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

DAY_TYPES = ("promo", "renovating", "closed")


class CalendarRuleIn(BaseModel):
    store_id: int = Field(ge=1)
    day_type: str = Field(default="promo", pattern=r"^(promo|renovating|closed)$")
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str | None = Field(default=None, min_length=10, max_length=10)
    label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    active: bool = True

    @model_validator(mode="after")
    def _dates(self):
        from src.utils.timeutil import parse_date

        start = parse_date(self.start_date)
        end = parse_date(self.end_date or self.start_date)
        if start is None:
            raise ValueError("start_date 必须为 YYYY-MM-DD")
        if end is None:
            raise ValueError("end_date 必须为 YYYY-MM-DD")
        if end < start:
            raise ValueError("end_date 不能早于 start_date")
        return self


class CalendarRulePatch(BaseModel):
    day_type: str | None = Field(default=None, pattern=r"^(promo|renovating|closed)$")
    start_date: str | None = Field(default=None, min_length=10, max_length=10)
    end_date: str | None = Field(default=None, min_length=10, max_length=10)
    label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
