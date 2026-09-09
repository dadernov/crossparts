from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Header, HTTPException, Request, status
from sqlalchemy import select

from .models import Account

from .config import get_settings


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest = stored.split("$", 1)
        candidate = hash_password(password, bytes.fromhex(salt_hex)).split("$", 1)[1]
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


async def require_tenant(request: Request, x_api_key: str | None = Header(default=None)) -> str:
    """Resolve the caller's tenant from ``X-API-Key``.

    An empty ``CP_API_KEYS`` disables auth, which is handy in development.
    """
    keys = get_settings().api_key_map
    username = request.session.get("username")
    if username:
        return username
    if not keys:
        return "default"
    if not x_api_key or x_api_key not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не указан или неверен заголовок X-API-Key",
        )
    return keys[x_api_key]


async def authenticate(session_factory, username: str, password: str) -> str | None:
    async with session_factory() as session:
        account = (await session.execute(
            select(Account).where(Account.username == username.strip().lower())
        )).scalar_one_or_none()
        if account and check_password(password, account.password_hash):
            return account.username
    return None
