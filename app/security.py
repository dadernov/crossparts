from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os

from fastapi import Header, HTTPException, Request, status
from sqlalchemy import select

from .models import Account

from .config import get_settings


GUEST_PREFIX = "guest-"


def client_ip(request: Request) -> str:
    """Return a canonical client address.

    Uvicorn trusts forwarded headers only from the local nginx proxy, so
    ``request.client.host`` is already the original visitor in production.
    """
    raw = request.client.host if request.client else "0.0.0.0"
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError:
        return "0.0.0.0"


def guest_tenant(request: Request) -> str:
    """Stable, non-reversible tenant key used for the IP-bound free quota."""
    secret = get_settings().session_secret.encode()
    digest = hmac.new(secret, client_ip(request).encode(), hashlib.sha256).hexdigest()[:40]
    return GUEST_PREFIX + digest


def is_guest_tenant(username: str) -> bool:
    return username.startswith(GUEST_PREFIX)


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
    """Resolve an account, API key, or IP-bound anonymous tenant."""
    keys = get_settings().api_key_map
    username = request.session.get("username")
    if username:
        return username
    if x_api_key:
        if x_api_key in keys:
            return keys[x_api_key]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не указан или неверен заголовок X-API-Key",
        )
    return guest_tenant(request)


async def authenticate(session_factory, username: str, password: str) -> str | None:
    async with session_factory() as session:
        account = (await session.execute(
            select(Account).where(Account.username == username.strip().lower())
        )).scalar_one_or_none()
        if account and check_password(password, account.password_hash):
            return account.username
    return None
