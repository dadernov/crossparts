from __future__ import annotations

from pydantic import BaseModel, Field


class LookupRequest(BaseModel):
    oe: str = Field(..., min_length=2, description="Оригинальный номер (OE/OEM)")
    sources: list[str] | None = Field(default=None, description="Ключи источников")
    fresh: bool = Field(default=False, description="Игнорировать кэш")
    group: str | None = Field(default=None,
                              description="Товарная группа: ключ или название из файла")


class JobItemIn(BaseModel):
    our_sku: str = ""
    oe_number: str
    group: str | None = None


class JobCreate(BaseModel):
    items: list[JobItemIn]
    sources: list[str] | None = None


class JobOut(BaseModel):
    id: str
    status: str
    total: int
    done: int
    sources: list[str]
    filename: str | None = None
    created_at: str
    finished_at: str | None = None
