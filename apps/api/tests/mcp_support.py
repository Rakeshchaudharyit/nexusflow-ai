"""Real MCP servers for tests: served over streamable HTTP by uvicorn on a loopback port."""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.applications import Starlette


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class LiveServer:
    port: int

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return f"http://{self.host}/mcp"


@contextmanager
def serve(app_factory) -> Iterator[LiveServer]:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            app_factory(f"127.0.0.1:{port}"), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Test MCP server did not start")
        time.sleep(0.02)
    try:
        yield LiveServer(port)
    finally:
        server.should_exit = True
        thread.join(5)


class Echo(BaseModel):
    value: str


def build_mutable_server() -> MCPServer:
    """A second server whose tool set tests change between discoveries."""
    server = MCPServer("nexusflow-test-mcp", version="1.0")

    @server.tool()
    def echo(value: str) -> Echo:
        """Echo a value."""
        return Echo(value=value)

    @server.tool()
    def slow() -> Echo:
        """Sleep longer than the test request timeout."""
        time.sleep(2)
        return Echo(value="late")

    return server


def http_app(server: MCPServer, host: str) -> Starlette:
    return server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(allowed_hosts=[host], allowed_origins=[]),
    )
