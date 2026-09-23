from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Account, Base, FeatureEntitlement
from .security import hash_password

_settings = get_settings()

if _settings.database_url.startswith("sqlite"):
    path = _settings.database_url.split("///")[-1]
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

engine = create_async_engine(_settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight forward migration for existing SQLite installations.
        if _settings.database_url.startswith("sqlite"):
            columns = (await conn.exec_driver_sql("PRAGMA table_info(job_items)")).all()
            if "part_name" not in {column[1] for column in columns}:
                await conn.exec_driver_sql(
                    "ALTER TABLE job_items ADD COLUMN part_name VARCHAR(255) NOT NULL DEFAULT ''"
                )
            account_columns = (await conn.exec_driver_sql("PRAGMA table_info(accounts)")).all()
            if "queries_used" not in {column[1] for column in account_columns}:
                await conn.exec_driver_sql(
                    "ALTER TABLE accounts ADD COLUMN queries_used INTEGER NOT NULL DEFAULT 0"
                )
            if "queries_limit" not in {column[1] for column in account_columns}:
                await conn.exec_driver_sql(
                    "ALTER TABLE accounts ADD COLUMN queries_limit INTEGER NOT NULL "
                    f"DEFAULT {max(1, _settings.requests_per_account)}"
                )
            job_columns = (await conn.exec_driver_sql("PRAGMA table_info(jobs)")).all()
            job_column_names = {column[1] for column in job_columns}
            if "batch_id" not in job_column_names:
                await conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN batch_id VARCHAR(32)")
            if "batch_role" not in job_column_names:
                await conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN batch_role VARCHAR(16)")
            if "batch_order" not in job_column_names:
                await conn.exec_driver_sql("ALTER TABLE jobs ADD COLUMN batch_order INTEGER")
            await conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_jobs_batch_id ON jobs (batch_id)"
            )
    async with SessionLocal() as session:
        for username, password in _settings.user_map.items():
            if await session.get(Account, username) is None:
                session.add(Account(username=username, password_hash=hash_password(password),
                                    queries_limit=_settings.requests_per_account))
        entitlement_key = "admin:vehicle_fitment"
        if await session.get(FeatureEntitlement, entitlement_key) is None:
            session.add(FeatureEntitlement(
                key=entitlement_key, tenant="admin", feature_key="vehicle_fitment",
                enabled=True, limits={"max_parts_per_job": 100},
            ))
        await session.commit()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
