from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, Index, Integer, String, Text
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
    # Large customer uploads are split into sequential, downloadable jobs.
    # The summary job is created only after every chunk has completed.
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    batch_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    batch_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

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
    queries_used: Mapped[int] = mapped_column(Integer, default=0)
    # A trial and a paid account have independent limits.
    queries_limit: Mapped[int] = mapped_column(Integer, default=1000)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenantDailyUsage(Base):
    """Persistent per-tenant pacing cursor for one UTC calendar day."""

    __tablename__ = "tenant_daily_usage"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    next_allowed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FeatureEntitlement(Base):
    """A manually assigned, independently expiring paid-module right."""

    __tablename__ = "feature_entitlements"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    feature_key: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limits: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_feature_entitlement_tenant_feature", FeatureEntitlement.tenant,
      FeatureEntitlement.feature_key, unique=True)


class FitmentPart(Base):
    """Unambiguous branded part identity used by applicability records."""

    __tablename__ = "fitment_parts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    brand_normalized: Mapped[str] = mapped_column(String(64), index=True)
    part_number_normalized: Mapped[str] = mapped_column(String(128), index=True)
    product_group: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_fitment_part_identity", FitmentPart.brand_normalized,
      FitmentPart.part_number_normalized, FitmentPart.product_group, unique=True)


class FitmentRecord(Base):
    """One normalized vehicle applicability relation without source-specific text."""

    __tablename__ = "fitment_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    part_id: Mapped[str] = mapped_column(ForeignKey("fitment_parts.id", ondelete="CASCADE"), index=True)
    identity_hash: Mapped[str] = mapped_column(String(64), index=True)
    make_normalized: Mapped[str] = mapped_column(String(128), index=True)
    model_normalized: Mapped[str] = mapped_column(String(255), index=True)
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_status: Mapped[str] = mapped_column(String(24), default="confirmed")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_fitment_record_identity", FitmentRecord.part_id,
      FitmentRecord.identity_hash, unique=True)


class FitmentEvidence(Base):
    """Reproducible proof that a source directly relates a part and vehicle."""

    __tablename__ = "fitment_evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    fitment_id: Mapped[str] = mapped_column(ForeignKey("fitment_records.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(64), index=True)
    source_product_id: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parser_version: Mapped[str] = mapped_column(String(32))
    raw_vehicle_label: Mapped[str] = mapped_column(Text, default="")
    raw_period: Mapped[str] = mapped_column(String(128), default="")
    match_basis: Mapped[str] = mapped_column(String(32), default="direct_product")


Index("ix_fitment_evidence_unique", FitmentEvidence.fitment_id,
      FitmentEvidence.source_key, FitmentEvidence.source_product_id,
      FitmentEvidence.parser_version, unique=True)


class FitmentJob(Base):
    """Persistent, restart-safe batch of explicit branded-part enrichments."""

    __tablename__ = "fitment_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_parts: Mapped[list] = mapped_column(JSON, default=list)
    results: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_fitment_job_idempotency", FitmentJob.tenant,
      FitmentJob.idempotency_key, unique=True)
