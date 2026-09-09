from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Job(Base):
    """A batch of OE numbers submitted by one tenant."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant: Mapped[str] = mapped_column(String(64), index=True, default="default")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["JobItem"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobItem.position"
    )


class JobItem(Base):
    """One (our SKU, OE number) pair and its aggregated result."""

    __tablename__ = "job_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    our_sku: Mapped[str] = mapped_column(String(128), default="")
    part_name: Mapped[str] = mapped_column(String(255), default="")
    oe_number: Mapped[str] = mapped_column(String(128), default="")
    #: Ключ товарной группы (app.groups) и исходный текст из файла заказчика.
    group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    group_raw: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    crosses: Mapped[list] = mapped_column(JSON, default=list)
    source_reports: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[Job] = relationship(back_populates="items")


class CacheEntry(Base):
    """Per-source lookup cache so repeat runs do not re-hit the catalogues."""

    __tablename__ = "cache_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(32), index=True)
    oe_key: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_cache_source_oe", CacheEntry.source, CacheEntry.oe_key, unique=True)


class Account(Base):
    """A client account. Its login is also the isolated tenant identifier."""

    __tablename__ = "accounts"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
