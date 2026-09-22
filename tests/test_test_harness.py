from __future__ import annotations

import socket
from pathlib import Path

import pytest


def test_database_is_forced_into_fresh_temporary_directory(isolated_test_root):
    from app.config import get_settings

    settings = get_settings()
    database = Path(settings.database_url.removeprefix("sqlite+aiosqlite:///")).resolve()
    assert database.parent == isolated_test_root
    assert database.name == "crossparts-test.db"
    assert database != Path("data/crossparts.db").resolve()


def test_offline_suite_rejects_external_dns_and_sockets():
    with pytest.raises(RuntimeError, match="external network is disabled"):
        socket.getaddrinfo("example.com", 443)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="external network is disabled"):
            sock.connect(("203.0.113.1", 443))
    finally:
        sock.close()


def test_offline_suite_keeps_loopback_available():
    infos = socket.getaddrinfo("localhost", 80)
    assert infos

