#!/usr/bin/env python3
"""Manually enable or disable an independently sold account feature."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from app.db import SessionLocal, init_db
from app.models import Account, FeatureEntitlement, utcnow


async def run(args) -> None:
    await init_db()
    tenant = args.tenant.strip().lower()
    async with SessionLocal() as session:
        if await session.get(Account, tenant) is None:
            raise SystemExit(f"Аккаунт {tenant!r} не найден")
        key = f"{tenant}:{args.feature}"
        grant = await session.get(FeatureEntitlement, key)
        expires_at = None
        if args.days is not None:
            expires_at = utcnow() + dt.timedelta(days=args.days)
        limits = {"max_parts_per_job": args.max_parts}
        if grant is None:
            grant = FeatureEntitlement(key=key, tenant=tenant, feature_key=args.feature)
            session.add(grant)
        grant.enabled = args.action == "enable"
        grant.expires_at = expires_at
        grant.limits = limits
        grant.updated_at = utcnow()
        await session.commit()
    print(f"{tenant}: {args.feature} = {grant.enabled}; expires={expires_at}; limits={limits}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("enable", "disable"))
    parser.add_argument("tenant")
    parser.add_argument("--feature", default="vehicle_fitment")
    parser.add_argument("--days", type=int)
    parser.add_argument("--max-parts", type=int, default=100)
    args = parser.parse_args()
    if args.max_parts < 1 or args.max_parts > 1000:
        parser.error("--max-parts должен быть от 1 до 1000")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
