import pytest

from app.mcp.errors import McpUrlRejected
from app.mcp.urls import UrlPolicy, validate_server_url

DEV = UrlPolicy(allowed_hosts=frozenset({"mcp-demo:8765"}))


def public_policy(*addresses: str) -> UrlPolicy:
    return UrlPolicy(allow_public_hosts=True, resolver=lambda host, port: list(addresses))


def test_explicitly_allowed_demo_host_is_accepted_and_normalized():
    assert validate_server_url("http://mcp-demo:8765/mcp", DEV) == "http://mcp-demo:8765/mcp"
    assert validate_server_url("HTTP://MCP-DEMO:8765/mcp", DEV) == "http://mcp-demo:8765/mcp"


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp-demo:9999/mcp",  # allowlist entries are host *and* port
        "http://localhost:8765/mcp",
        "http://127.0.0.1:8765/mcp",
        "http://[::1]:8765/mcp",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/mcp",
        "http://192.168.1.10/mcp",
        "http://postgres:5432/",
        "http://redis:6379/",
        "https://example.com/mcp",  # public hosts are off unless explicitly enabled
    ],
)
def test_default_policy_rejects_everything_not_allowlisted(url):
    with pytest.raises(McpUrlRejected):
        validate_server_url(url, DEV)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://mcp-demo:8765/_",
        "ftp://mcp-demo:8765/",
        "unix:///var/run/docker.sock",
        "http+unix://%2Fvar%2Frun%2Fdocker.sock/info",
        "ws://mcp-demo:8765/mcp",
        "http://user:secret@mcp-demo:8765/mcp",
        "http://mcp-demo:8765/mcp?token=secret",
        "http://mcp-demo:8765/mcp#fragment",
        "http://mcp-demo:8765/mc p",
        "http://mcp-demo:99999/mcp",
        "http:///mcp",
        "http://mcp-demo:8765/" + "a" * 2100,
    ],
)
def test_malformed_or_unsupported_urls_are_rejected_even_for_allowlisted_hosts(url):
    with pytest.raises(McpUrlRejected):
        validate_server_url(url, DEV)


def test_public_https_host_resolving_to_public_addresses_is_accepted_when_enabled():
    policy = public_policy("93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c")
    assert validate_server_url("https://tools.example.com/mcp", policy) == (
        "https://tools.example.com/mcp"
    )


@pytest.mark.parametrize(
    "url,addresses",
    [
        ("http://tools.example.com/mcp", ["93.184.215.14"]),  # public servers need https
        ("https://tools.example.com/mcp", ["127.0.0.1"]),
        ("https://tools.example.com/mcp", ["93.184.215.14", "10.1.2.3"]),  # any private answer
        ("https://tools.example.com/mcp", ["169.254.169.254"]),
        ("https://tools.example.com/mcp", ["::ffff:127.0.0.1"]),
        ("https://tools.example.com/mcp", ["fd00::1"]),
        ("https://tools.example.com/mcp", ["100.64.0.1"]),
        ("https://tools.example.com/mcp", []),
        ("https://127.0.0.1/mcp", []),
        ("https://[::1]/mcp", []),
        ("https://169.254.169.254/mcp", []),
        ("https://localhost/mcp", []),
        ("https://metadata.google.internal/mcp", ["93.184.215.14"]),
        ("https://printer.local/mcp", ["93.184.215.14"]),
        ("https://intranet/mcp", ["93.184.215.14"]),
    ],
)
def test_public_mode_still_blocks_internal_destinations(url, addresses):
    with pytest.raises(McpUrlRejected):
        validate_server_url(url, public_policy(*addresses))


def test_unresolvable_public_host_is_rejected():
    def fail(host, port):
        raise OSError("no such host")

    with pytest.raises(McpUrlRejected):
        validate_server_url(
            "https://missing.example.com/mcp", UrlPolicy(allow_public_hosts=True, resolver=fail)
        )


def test_rejection_message_does_not_echo_the_url():
    with pytest.raises(McpUrlRejected) as error:
        validate_server_url("http://user:hunter2@10.0.0.1/mcp", DEV)
    assert "hunter2" not in error.value.message
    assert "10.0.0.1" not in error.value.message
