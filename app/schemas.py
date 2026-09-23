from __future__ import annotations

from pydantic import BaseModel, Field


class LookupRequest(BaseModel):
    oe: str = Field(..., min_length=2, description="Оригинальный номер (OE/OEM)")
    sources: list[str] | None = Field(default=None, description="Ключи источников")
    group: str | None = Field(default=None,
                              description="Товарная группа: ключ или название из файла")


class FitmentLookupRequest(BaseModel):
    brand: str = Field(..., min_length=2, max_length=64)
    number: str = Field(..., min_length=2, max_length=128)
    group: str = Field(..., description="Товарная группа найденной детали")


class LookupExportCross(BaseModel):
    brand: str = ""
    number: str = ""
    kind: str | None = None
    sources: list[str] = Field(default_factory=list)


class LookupExportRequest(BaseModel):
    oe_number: str = Field(..., min_length=2)
    group: str | None = None
    group_raw: str = ""
    crosses: list[LookupExportCross] = Field(default_factory=list)


class JobItemIn(BaseModel):
    our_sku: str = ""
    part_name: str = ""
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
