from __future__ import annotations

from pydantic import BaseModel, Field


class RunIn(BaseModel):
    store_id: int | None = Field(default=None, ge=1)
    trigger: str = Field(default="manual", pattern=r"^(manual|schedule|seed)$")
    metrics: list[str] = Field(default_factory=lambda: ["rev"])
    window: int = Field(default=28, ge=7, le=90)
    threshold: float = Field(default=3.5, ge=1.0, le=10.0)
    persist_z: float = Field(default=1.5, ge=0.0, le=10.0)
    stratify: bool = True
