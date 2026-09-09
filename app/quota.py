"""Per-account search quota. A batch reserves all its OE positions atomically."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import update

from .models import Account


async def reserve_queries(session_factory, username: str, count: int, limit: int) -> int:
    """Reserve ``count`` positions and return the remaining balance.

    The conditional update prevents two browser tabs from spending more than the
    configured account limit at the same time.
    """
    async with session_factory() as session:
        result = await session.execute(
            update(Account)
            .where(Account.username == username, Account.queries_used + count <= limit)
            .values(queries_used=Account.queries_used + count)
        )
        if result.rowcount != 1:
            await session.rollback()
            raise HTTPException(
                429,
                f"Лимит {limit:,} поисков исчерпан. Обратитесь к менеджеру, чтобы продлить доступ.".replace(",", " "),
            )
        account = await session.get(Account, username)
        await session.commit()
        return limit - account.queries_used


async def quota_status(session_factory, username: str, limit: int) -> dict:
    async with session_factory() as session:
        account = await session.get(Account, username)
        used = account.queries_used if account else 0
    return {"limit": limit, "used": used, "remaining": max(0, limit - used)}
