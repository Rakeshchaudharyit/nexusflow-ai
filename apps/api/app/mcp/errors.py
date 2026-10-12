from app.agents.errors import ToolExecutionError


class McpError(ToolExecutionError):
    """MCP failure with a safe, persistable code and message.

    Subclasses ToolExecutionError so the agent runtime fails a run with it unchanged.
    """

    code = "mcp_error"
    message = "The MCP server request failed."
    # True when the failure means the server could not be used at all (marks it unavailable);
    # False when the server answered and only this call failed.
    connectivity = False


class McpUrlRejected(McpError):
    code = "mcp_url_rejected"
    message = "This MCP server URL is not permitted."
    connectivity = True


class McpUnavailable(McpError):
    code = "mcp_unavailable"
    message = "The MCP server could not be reached."
    connectivity = True


class McpTimeout(McpError):
    code = "mcp_timeout"
    message = "The MCP server did not respond in time."
    connectivity = True


class McpProtocolError(McpError):
    code = "mcp_protocol_error"
    message = "The MCP server returned an invalid protocol response."
    connectivity = True


class McpToolNotFound(McpError):
    code = "mcp_tool_not_found"
    message = "The MCP tool is not available on the server."


class McpToolDisabled(McpError):
    code = "mcp_tool_disabled"
    message = "The MCP tool is disabled."


class McpServerDisabled(McpError):
    code = "mcp_server_disabled"
    message = "The MCP server is disabled."


class McpToolFailed(McpError):
    code = "mcp_tool_error"
    message = "The MCP tool reported an error."


class McpMalformedResult(McpError):
    code = "mcp_malformed_result"
    message = "The MCP tool returned a result that does not match its schema."
