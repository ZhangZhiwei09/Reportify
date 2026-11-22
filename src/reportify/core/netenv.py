"""Network environment guards.

A system proxy (common with VPN/clash clients) captures requests to loopback,
which makes local MCP servers unreachable and surfaces as an opaque 502 from the
proxy. Loopback must always bypass the proxy.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def ensure_loopback_bypasses_proxy() -> list[str]:
    """Append loopback hosts to ``NO_PROXY``/``no_proxy``; return added hosts."""
    added: list[str] = []
    for variable in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(variable, "")
        entries = [item.strip() for item in current.split(",") if item.strip()]
        lower = {item.lower() for item in entries}
        for host in LOOPBACK_HOSTS:
            if host.lower() not in lower:
                entries.append(host)
                added.append(host)
        os.environ[variable] = ",".join(entries)
    if added:
        logger.debug("added loopback hosts to NO_PROXY: %s", sorted(set(added)))
    return sorted(set(added))
