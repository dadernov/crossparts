"""Per-account search quota. A batch reserves all its OE positions atomically."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update

from .models import Account
from .security import is_guest_tenant


async def _ensure_guest_account(session_factory, username: str, limit: int) -> None:
    if not is_guest_tenant(username):
        return
    async with session_factory() as session:
        if await session.get(Account, username) is not None:
            return
        session.add(Account(username=username, password_hash="guest", queries_limit=limit))
        try:
            await session.commit()
        except IntegrityError:
            # Another request from the same IP created the quota row first.
            await session.rollback()


async def reserve_queries(session_factory, username: str, count: int, limit: int) -> int:
    """Reserve ``count`` positions and return the remaining balance.

    The conditional update prevents two browser tabs from spending more than the
    account limit at the same time. ``limit`` remains a fallback for old data.
    """
    await _ensure_guest_account(session_factory, username, limit)
    async with session_factory() as session:
        result = await session.execute(
            update(Account)
            .where(Account.username == username, Account.queries_used + count <= Account.queries_limit)
            .values(queries_used=Account.queries_used + count)
        )
        if result.rowcount != 1:
            await session.rollback()
            raise HTTPException(
                429,
                "Лимит поисков исчерпан. Обратитесь к менеджеру, чтобы продлить доступ.",
            )
        account = await session.get(Account, username)
        await session.commit()
        return max(0, (account.queries_limit or limit) - account.queries_used)


async def quota_status(session_factory, username: str, limit: int) -> dict:
    async with session_factory() as session:
        account = await session.get(Account, username)
        used = account.queries_used if account else 0
        account_limit = account.queries_limit if account else limit
    return {"limit": account_limit, "used": used, "remaining": max(0, account_limit - used)}
