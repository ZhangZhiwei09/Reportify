"""SSRF guard for every outbound URL (03 §11.2).

Applies to MCP endpoints and to each URL in the OAuth discovery chain. The rule
is explicit: only ``https`` (plus loopback in local mode), no userinfo, and no
DNS answer may land in a private, loopback, link-local, multicast or reserved
network — including the cloud metadata address.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_REDIRECTS = 3

_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, includes cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
)

# Hosts that must never resolve to a permitted target, even in local mode.
METADATA_HOSTNAMES = frozenset(
    {"metadata.google.internal", "metadata", "instance-data", "169.254.169.254"}
)

LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1"})


class SSRFError(ValueError):
    """An outbound URL failed the SSRF policy."""

    code = "forbidden"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ValidatedURL:
    url: str
    scheme: str
    host: str
    port: int | None
    addresses: tuple[str, ...]

    @property
    def origin(self) -> tuple[str, str, int | None]:
        return (self.scheme, self.host.lower(), self.port)


def resolve_host(host: str) -> list[str]:
    """Resolve a hostname to every address the platform would connect to."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"host does not resolve: {host}") from exc
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise SSRFError(f"host does not resolve: {host}")
    return addresses


def parse_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(value)


def is_blocked_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    *,
    allow_loopback: bool = False,
) -> bool:
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_loopback:
        return not allow_loopback
    return any(address in network for network in _BLOCKED_NETWORKS)


def validate_url(
    url: str,
    *,
    allow_loopback: bool = False,
    resolver: Callable[[str], list[str]] = resolve_host,
) -> ValidatedURL:
    """Validate one URL and return the addresses it may connect to."""
    if not url or len(url) > 2048:
        raise SSRFError("url is empty or too long")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").strip().lower()

    if not host:
        raise SSRFError("url has no host")
    if parts.username or parts.password or "@" in parts.netloc:
        raise SSRFError("url must not contain userinfo")
    if scheme == "https":
        pass
    elif scheme == "http" and allow_loopback and host in LOOPBACK_HOSTNAMES:
        pass
    else:
        raise SSRFError(f"scheme {scheme!r} is not allowed")

    if parts.port is not None and not (1 <= parts.port <= 65535):
        raise SSRFError("url has an invalid port")
    if host in METADATA_HOSTNAMES:
        raise SSRFError("cloud metadata host is not allowed")

    if host in LOOPBACK_HOSTNAMES:
        if not allow_loopback:
            raise SSRFError("loopback target is not allowed")
        addresses = ["127.0.0.1"]
    else:
        addresses = resolver(host)

    for address in addresses:
        parsed = parse_address(address)
        if is_blocked_address(parsed, allow_loopback=allow_loopback):
            raise SSRFError(f"address {address} is not allowed")

    return ValidatedURL(
        url=url,
        scheme=scheme,
        host=host,
        port=parts.port,
        addresses=tuple(addresses),
    )


def validate_redirect_chain(
    urls: Iterable[str],
    *,
    allow_loopback: bool = False,
    resolver: Callable[[str], list[str]] = resolve_host,
    max_redirects: int = MAX_REDIRECTS,
) -> list[ValidatedURL]:
    """Validate a redirect chain: every hop re-checked, no cross-origin hop."""
    chain: list[ValidatedURL] = []
    origin: tuple[str, str, int | None] | None = None
    for index, url in enumerate(urls):
        if index > max_redirects:
            raise SSRFError(f"redirect chain exceeds {max_redirects} hops")
        validated = validate_url(url, allow_loopback=allow_loopback, resolver=resolver)
        if origin is None:
            origin = validated.origin
        elif validated.origin != origin:
            raise SSRFError(f"cross-origin redirect is not allowed: {url}")
        chain.append(validated)
    if not chain:
        raise SSRFError("redirect chain is empty")
    return chain
