from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import get_settings


async def require_tenant(x_api_key: str | None = Header(default=None)) -> str:
    """Resolve the caller's tenant from ``X-API-Key``.

    An empty ``CP_API_KEYS`` disables auth, which is handy in development.
    """
    keys = get_settings().api_key_map
    if not keys:
        return "default"
    if not x_api_key or x_api_key not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не указан или неверен заголовок X-API-Key",
        )
    return keys[x_api_key]
