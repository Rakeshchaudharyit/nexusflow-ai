"""Synchronous facade over the official MCP Python SDK (v2) streamable HTTP client.

Every operation opens one short-lived session: validate the URL, connect, perform the request
and close. There are no retries and no shared connections, and each operation runs under one
overall deadline. The facade is synchronous so the runtime and services stay synchronous; each
call runs its own event loop via `anyio.run`, which is valid on any thread without a running
loop, including FastAPI's worker threads.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, TypeVar

import anyio
import httpx2
import pydantic
from mcp.client import Client
from mcp.client.streamable_http import StreamableHTTPError, streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import Implementation, TextContent

from app.mcp.errors import (
    McpError,
    McpMalformedResult,
    McpProtocolError,
    McpTimeout,
    McpToolFailed,
    McpToolNotFound,
    McpUnavailable,
)
from app.mcp.urls import UrlPolicy, validate_server_url

logger = logging.getLogger(__name__)
T = TypeVar("T")
REQUEST_TIMEOUT_CODE = -32001
MAX_TOOL_PAGES = 10
MAX_RESULT_BYTES = 64 * 1024
CLIENT_INFO = Implementation(name="nexusflow-api", version="0.4.0")


@dataclass(frozen=True)
class McpTimeouts:
    connect_seconds: float
    request_seconds: float

    @property
    def total_seconds(self) -> float:
        return self.connect_seconds + self.request_seconds


@dataclass(frozen=True)
class ServerProbe:
    name: str | None
    version: str | None
    protocol_version: str
    duration_ms: int


@dataclass(frozen=True)
class RemoteTool:
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None


@dataclass(frozen=True)
class ToolListing:
    server: ServerProbe
    tools: list[RemoteTool]


@dataclass(frozen=True)
class ToolCallOutcome:
    output: dict[str, Any]
    duration_ms: int


def leaf_exceptions(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in leaf_exceptions(inner)]
    return [error]


def classify(error: BaseException) -> McpError:
    """Map SDK, transport and timeout failures to safe errors. Prefers the most specific."""
    leaves = leaf_exceptions(error)
    for leaf in leaves:
        if isinstance(leaf, McpError):
            return leaf
    for leaf in leaves:
        if isinstance(leaf, TimeoutError | httpx2.TimeoutException) or (
            isinstance(leaf, MCPError) and leaf.code == REQUEST_TIMEOUT_CODE
        ):
            return McpTimeout()
    for leaf in leaves:
        if isinstance(leaf, httpx2.TransportError | OSError):
            return McpUnavailable()
    for leaf in leaves:
        if isinstance(leaf, MCPError | StreamableHTTPError | httpx2.HTTPError):
            return McpProtocolError()
        if isinstance(leaf, pydantic.ValidationError | ValueError | RuntimeError):
            return McpProtocolError()
    logger.error("Unclassified MCP client failure (%s)", type(error).__name__)
    return McpProtocolError()


def tool_error_message(result: Any, tool: str) -> str:
    text = " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    ).strip()
    text = re.sub(rf"^Error executing tool {re.escape(tool)}:\s*", "", text)
    text = re.sub(r"\s+", " ", text)[:200]
    return f"MCP tool error: {text}" if text else McpToolFailed.message


def result_payload(result: Any) -> dict[str, Any]:
    if result.structured_content is not None:
        payload = result.structured_content
    else:
        text = "".join(
            block.text for block in result.content if isinstance(block, TextContent)
        ).strip()
        if not text:
            raise McpMalformedResult("The MCP tool returned no usable content.")
        payload = {"text": text}
    if not isinstance(payload, dict):
        raise McpMalformedResult("The MCP tool returned a non-object result.")
    if len(json.dumps(payload, default=str)) > MAX_RESULT_BYTES:
        raise McpMalformedResult("The MCP tool result exceeds the size limit.")
    return payload


class McpClient:
    def __init__(self, policy: UrlPolicy, timeouts: McpTimeouts):
        self._policy = policy
        self._timeouts = timeouts

    def _run(self, url: str, operation: Callable[[Client], Awaitable[T]]) -> tuple[T, int]:
        target = validate_server_url(url, self._policy)
        started = perf_counter()
        try:
            value = anyio.run(self._session, target, operation)
        except McpError:
            raise
        except Exception as error:
            raise classify(error) from None
        return value, round((perf_counter() - started) * 1000)

    async def _session(self, url: str, operation: Callable[[Client], Awaitable[T]]) -> T:
        timeout = httpx2.Timeout(
            self._timeouts.request_seconds, connect=self._timeouts.connect_seconds
        )
        with anyio.fail_after(self._timeouts.total_seconds):
            # trust_env=False: ignore proxy variables so traffic only goes to the validated host.
            async with httpx2.AsyncClient(timeout=timeout, trust_env=False) as http:
                transport = streamable_http_client(url, http_client=http, terminate_on_close=False)
                async with Client(
                    transport,
                    read_timeout_seconds=self._timeouts.request_seconds,
                    cache=None,
                    client_info=CLIENT_INFO,
                ) as client:
                    return await operation(client)

    @staticmethod
    def _probe(client: Client, duration_ms: int = 0) -> ServerProbe:
        info = client.server_info
        return ServerProbe(
            name=info.name if info else None,
            version=info.version if info else None,
            protocol_version=client.protocol_version,
            duration_ms=duration_ms,
        )

    @staticmethod
    async def _list(client: Client) -> list[Any]:
        tools: list[Any] = []
        cursor = None
        for _ in range(MAX_TOOL_PAGES):
            page = await client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if cursor is None:
                return tools
        raise McpProtocolError("The MCP server returned too many tool pages.")

    def probe(self, url: str) -> ServerProbe:
        async def operation(client: Client) -> ServerProbe:
            # Opening the session performs the protocol handshake (server/discover on modern
            # servers, initialize on legacy ones); ping no longer exists as of 2026-07-28.
            return self._probe(client)

        probe, duration = self._run(url, operation)
        return ServerProbe(probe.name, probe.version, probe.protocol_version, duration)

    def list_tools(self, url: str) -> ToolListing:
        async def operation(client: Client) -> ToolListing:
            tools = await self._list(client)
            return ToolListing(
                server=self._probe(client),
                tools=[
                    RemoteTool(
                        name=tool.name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                        output_schema=tool.output_schema,
                    )
                    for tool in tools
                ],
            )

        listing, duration = self._run(url, operation)
        server = listing.server
        return ToolListing(
            ServerProbe(server.name, server.version, server.protocol_version, duration),
            listing.tools,
        )

    def call_tool(self, url: str, name: str, arguments: dict[str, Any]) -> ToolCallOutcome:
        """Call `name` after confirming the live server still lists it."""

        async def operation(client: Client) -> dict[str, Any]:
            if not any(tool.name == name for tool in await self._list(client)):
                raise McpToolNotFound()
            result = await client.call_tool(name, arguments)
            if result.is_error:
                raise McpToolFailed(tool_error_message(result, name))
            return result_payload(result)

        output, duration = self._run(url, operation)
        return ToolCallOutcome(output=output, duration_ms=duration)
