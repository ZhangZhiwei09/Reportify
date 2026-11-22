"""A real MCP server (streamable HTTP) for integration tests.

Not a mock: it speaks the protocol over a loopback port, so discovery, calling,
timeouts and schema drift exercise the same code path as production.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeMCPServer:
    def __init__(self) -> None:
        self.server = MCPServer("reportify-fake")
        self.calls: list[str] = []
        self._register_defaults()
        self.app = self.server.streamable_http_app()
        self.port = free_port()
        self._uvicorn = uvicorn.Server(
            uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error")
        )
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> FakeMCPServer:
        self._thread = threading.Thread(target=self._uvicorn.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if getattr(self._uvicorn, "started", False):
                return self
            time.sleep(0.05)
        raise RuntimeError("fake MCP server did not start")

    def stop(self) -> None:
        self._uvicorn.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    # ---------------------------------------------------------------- tools

    def _register_defaults(self) -> None:
        calls = self.calls

        @self.server.tool()
        def echo(text: str) -> str:
            """Echo the text back."""
            calls.append(f"echo:{text}")
            return f"echo:{text}"

        @self.server.tool()
        def slow(seconds: float = 3.0) -> str:
            """Sleep, then answer. Used to exercise read timeouts."""
            time.sleep(seconds)
            return "slept"

        @self.server.tool()
        def boom() -> str:
            """Always raises, to exercise tool error mapping."""
            raise RuntimeError("boom")

    def add_tool(self, name: str, fn: Callable[..., Any]) -> None:
        self.server.add_tool(fn, name=name)

    def remove_tool(self, name: str) -> None:
        self.server.remove_tool(name)

    def mutate_echo_description(self) -> None:
        """Change a tool's schema to simulate drift."""

        def echo(text: str, suffix: str = "") -> str:
            """Echo with an optional suffix (schema changed)."""
            return f"echo:{text}{suffix}"

        self.server.remove_tool("echo")
        self.server.add_tool(echo, name="echo")


def closed_port_url() -> str:
    """A loopback URL nothing listens on."""
    return f"http://127.0.0.1:{free_port()}/mcp"
