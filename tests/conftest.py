"""Global safety rails for the test suite.

The application builds its database engine while modules are imported.  These
variables therefore have to be set from ``conftest.py``, before pytest imports
any test module that imports ``app.main`` or ``app.db``.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from pathlib import Path

import pytest


_TEST_ROOT = Path(tempfile.mkdtemp(prefix="crossparts-tests-")).resolve()
_TEST_DATABASE = _TEST_ROOT / "crossparts-test.db"

# Never inherit production state when pytest is launched from a production
# shell.  Every test process receives a fresh database and harmless accounts.
os.environ["CP_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DATABASE}"
os.environ["CP_API_KEYS"] = "test-key:pytest"
os.environ["CP_USERS"] = "pytest:pytest"
os.environ["CP_SESSION_SECRET"] = "pytest-session-secret-not-for-production"
os.environ["CP_PROXY_URL"] = ""
os.environ["CP_PROXY_SOURCES"] = ""
os.environ["CP_BROWSER_FALLBACK"] = "false"


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(request, monkeypatch):
    """Forbid external sockets unless a test is explicitly marked ``live``.

    Loopback stays available for ASGI/local mock servers and Playwright's local
    browser transport.  Live tests additionally require the exact opt-in value
    ``CP_LIVE=1`` and are skipped otherwise by their own module marker.
    """
    if request.node.get_closest_marker("live") is not None:
        return

    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_loopback(host):
            raise RuntimeError(f"external network is disabled in offline tests: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) and address else None
            if not _is_loopback(host):
                raise RuntimeError(
                    f"external network is disabled in offline tests: {host!r}"
                )
        return real_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) and address else None
            if not _is_loopback(host):
                raise RuntimeError(
                    f"external network is disabled in offline tests: {host!r}"
                )
        return real_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture(scope="session")
def isolated_test_root() -> Path:
    return _TEST_ROOT

