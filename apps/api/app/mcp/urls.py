"""Outbound URL policy for MCP servers.

MCP server URLs are tenant-supplied, so every connection is checked here first to avoid
turning the API into a request-forgery primitive. The rules, in order:

1. http(s) only; no credentials, query string or fragment; bounded length.
2. A host:port on the operator-configured allowlist (MCP_ALLOWED_HOSTS) is accepted as-is. This
   is the only way to reach private addresses, such as the Compose `mcp-demo` service.
3. Anything else needs MCP_ALLOW_PUBLIC_HOSTS=true, HTTPS, a non-internal hostname, and DNS
   answers that are all publicly routable addresses.
"""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.mcp.errors import McpUrlRejected

MAX_URL_LENGTH = 2048
DEFAULT_PORTS = {"http": 80, "https": 443}
INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".lan", ".corp")
Resolver = Callable[[str, int], list[str]]


def resolve_addresses(host: str, port: int) -> list[str]:
    return list({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


@dataclass(frozen=True)
class UrlPolicy:
    allowed_hosts: frozenset[str] = frozenset()
    allow_public_hosts: bool = False
    resolver: Resolver = field(default=resolve_addresses, compare=False)


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def rejected(reason: str) -> McpUrlRejected:
    return McpUrlRejected(f"This MCP server URL is not permitted: {reason}.")


def validate_server_url(raw: str, policy: UrlPolicy) -> str:
    """Return the normalized URL, or raise McpUrlRejected."""
    if len(raw) > MAX_URL_LENGTH or any(ord(char) < 33 for char in raw):
        raise rejected("malformed URL")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as error:
        raise rejected("malformed URL") from error
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise rejected("only http and https are supported")
    if parts.username is not None or parts.password is not None:
        raise rejected("credentials in URLs are not allowed")
    if parts.query or parts.fragment:
        raise rejected("query strings and fragments are not allowed")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise rejected("a host is required")
    port = port or DEFAULT_PORTS[scheme]
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc += f":{port}"
    normalized = f"{scheme}://{netloc}{parts.path or '/'}"

    if f"{host}:{port}" in policy.allowed_hosts:
        return normalized
    if not policy.allow_public_hosts:
        raise rejected("the host is not on the MCP allowlist")
    if scheme != "https":
        raise rejected("public MCP servers must use https")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public(host):
            raise rejected("private, loopback and link-local addresses are not allowed")
        return normalized
    if host == "localhost" or host.endswith(INTERNAL_SUFFIXES) or "." not in host:
        raise rejected("internal hostnames are not allowed")
    try:
        addresses = policy.resolver(host, port)
    except OSError as error:
        raise rejected("the host could not be resolved") from error
    if not addresses or not all(is_public(address) for address in addresses):
        raise rejected("the host resolves to a non-public address")
    return normalized
