from __future__ import annotations

import os

from reportify.core.netenv import LOOPBACK_HOSTS, ensure_loopback_bypasses_proxy


def test_appends_loopback_hosts(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.setenv("no_proxy", "example.com")

    added = ensure_loopback_bypasses_proxy()

    assert set(added) == set(LOOPBACK_HOSTS)
    for variable in ("NO_PROXY", "no_proxy"):
        entries = os.environ[variable].split(",")
        assert entries[0] == "example.com"
        for host in LOOPBACK_HOSTS:
            assert host in entries


def test_is_idempotent(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1")

    assert ensure_loopback_bypasses_proxy() == []
    assert os.environ["NO_PROXY"] == "127.0.0.1,localhost,::1"


def test_handles_empty_and_spaced_values(monkeypatch) -> None:
    # Windows environment variables are case-insensitive, so setting only the
    # upper-case name is the portable way to seed this test.
    monkeypatch.setenv("NO_PROXY", " , internal.test , ")

    ensure_loopback_bypasses_proxy()

    entries = [item.strip() for item in os.environ["NO_PROXY"].split(",") if item.strip()]
    assert "internal.test" in entries
    assert set(LOOPBACK_HOSTS) <= set(entries)
