from __future__ import annotations

from pydantic import BaseModel, Field


class StoreIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=2, max_length=120)
    region: str = Field(min_length=2, max_length=40)
    city: str = Field(min_length=1, max_length=40)
    brand: str = Field(default="蓝湾精选", max_length=40)
    room_count: int = Field(default=200, ge=1, le=2000)
    manager: str = Field(default="", max_length=60)
    status: str = Field(default="open", pattern=r"^(open|renovating|closed)$")
    note: str | None = Field(default=None, max_length=2000)


class StorePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    region: str | None = Field(default=None, min_length=2, max_length=40)
    city: str | None = Field(default=None, min_length=1, max_length=40)
    brand: str | None = Field(default=None, max_length=40)
    room_count: int | None = Field(default=None, ge=1, le=2000)
    manager: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, pattern=r"^(open|renovating|closed)$")
    note: str | None = Field(default=None, max_length=2000)
