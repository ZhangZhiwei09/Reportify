from __future__ import annotations

import pytest

from reportify.core.ssrf import (
    SSRFError,
    is_blocked_address,
    parse_address,
    validate_redirect_chain,
    validate_url,
)


def _resolver(mapping: dict[str, list[str]]):
    def _resolve(host: str) -> list[str]:
        if host not in mapping:
            raise SSRFError(f"host does not resolve: {host}")
        return mapping[host]

    return _resolve


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://example.com/x", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("http://example.com/x", "scheme"),
        ("https://user:pass@example.com/x", "userinfo"),
        ("https://example.com@evil.test/x", "userinfo"),
        ("https://169.254.169.254/latest/meta-data/", "address"),
        ("https://metadata.google.internal/", "metadata"),
        ("https://127.0.0.1/x", "loopback"),
        ("https://[::1]/x", "loopback"),
    ],
)
def test_rejects_unsafe_urls(url: str, reason: str) -> None:
    with pytest.raises(SSRFError):
        validate_url(url, allow_loopback=False, resolver=_resolver({}))


def test_metadata_host_is_rejected_even_with_loopback_allowed() -> None:
    with pytest.raises(SSRFError):
        validate_url(
            "http://169.254.169.254/latest",
            allow_loopback=True,
            resolver=_resolver({}),
        )


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "172.16.5.4",
        "192.168.1.1",
        "100.64.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "fc00::1",
        "fe80::1",
        "::1",
    ],
)
def test_private_networks_are_blocked(address: str) -> None:
    assert is_blocked_address(parse_address(address), allow_loopback=False) is True


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_blocked_address(parse_address(address), allow_loopback=False) is False


def test_dns_answer_landing_in_private_network_is_rejected() -> None:
    resolver = _resolver({"internal.example.com": ["93.184.216.34", "10.1.2.3"]})
    with pytest.raises(SSRFError):
        validate_url("https://internal.example.com/mcp", resolver=resolver)


def test_public_host_is_accepted() -> None:
    resolver = _resolver({"mcp.example.com": ["93.184.216.34"]})
    validated = validate_url("https://mcp.example.com/mcp", resolver=resolver)
    assert validated.host == "mcp.example.com"
    assert validated.addresses == ("93.184.216.34",)


def test_loopback_allowed_in_local_mode() -> None:
    validated = validate_url(
        "http://127.0.0.1:8765/mcp",
        allow_loopback=True,
        resolver=_resolver({}),
    )
    assert validated.port == 8765


def test_http_loopback_rejected_when_local_mode_off() -> None:
    with pytest.raises(SSRFError):
        validate_url(
            "http://localhost:8765/mcp",
            allow_loopback=False,
            resolver=_resolver({}),
        )


def test_unresolvable_host_is_rejected() -> None:
    with pytest.raises(SSRFError):
        validate_url("https://nowhere.test/mcp", resolver=_resolver({}))


def test_redirect_chain_same_origin_is_accepted() -> None:
    resolver = _resolver({"mcp.example.com": ["93.184.216.34"]})
    chain = validate_redirect_chain(
        [
            "https://mcp.example.com/a",
            "https://mcp.example.com/b",
        ],
        resolver=resolver,
    )
    assert len(chain) == 2


def test_redirect_chain_rejects_cross_origin() -> None:
    resolver = _resolver(
        {
            "mcp.example.com": ["93.184.216.34"],
            "evil.example.net": ["93.184.216.35"],
        }
    )
    with pytest.raises(SSRFError, match="cross-origin"):
        validate_redirect_chain(
            ["https://mcp.example.com/a", "https://evil.example.net/b"],
            resolver=resolver,
        )


def test_redirect_chain_rejects_too_many_hops() -> None:
    resolver = _resolver({"mcp.example.com": ["93.184.216.34"]})
    with pytest.raises(SSRFError, match="exceeds"):
        validate_redirect_chain(
            [f"https://mcp.example.com/{index}" for index in range(5)],
            resolver=resolver,
        )


def test_redirect_chain_revalidates_every_hop() -> None:
    resolver = _resolver({"mcp.example.com": ["93.184.216.34"]})
    with pytest.raises(SSRFError):
        validate_redirect_chain(
            ["https://mcp.example.com/a", "https://169.254.169.254/b"],
            resolver=resolver,
        )
