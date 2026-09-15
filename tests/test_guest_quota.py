import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.models import Base
from app.quota import quota_status, reserve_queries
from app.security import guest_tenant


def request_from(ip: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                    "client": (ip, 4321), "server": ("test", 443), "scheme": "https"})


@pytest.mark.asyncio
async def test_guest_quota_is_stable_and_bound_to_ip(tmp_path):
    first = guest_tenant(request_from("203.0.113.10"))
    assert first == guest_tenant(request_from("203.0.113.10"))
    assert first != guest_tenant(request_from("203.0.113.11"))
    assert "203.0.113.10" not in first

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/guest.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    assert await quota_status(sessions, first, 10) == {"limit": 10, "used": 0, "remaining": 10}
    for remaining in range(9, -1, -1):
        assert await reserve_queries(sessions, first, 1, 10) == remaining
    with pytest.raises(HTTPException) as error:
        await reserve_queries(sessions, first, 1, 10)
    assert error.value.status_code == 429
    assert (await quota_status(sessions, first, 10))["remaining"] == 0
    await engine.dispose()
