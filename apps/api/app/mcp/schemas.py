"""Validation of untrusted MCP metadata and arguments."""

import json
import logging
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.mcp.client import RemoteTool

logger = logging.getLogger(__name__)
TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
MAX_SCHEMA_BYTES = 32 * 1024
MAX_DESCRIPTION = 1000
MAX_TOOLS = 200


def valid_schema(schema: Any) -> bool:
    if not isinstance(schema, dict) or len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
        return False
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return False
    return True


def normalize_tools(tools: list[RemoteTool]) -> list[RemoteTool]:
    """Keep well-formed tools; drop (and log) the rest rather than storing unsafe metadata."""
    accepted: dict[str, RemoteTool] = {}
    for tool in tools[:MAX_TOOLS]:
        if not TOOL_NAME.fullmatch(tool.name) or tool.name in accepted:
            logger.warning("Skipping MCP tool with invalid or duplicate name")
            continue
        if not valid_schema(tool.input_schema) or tool.input_schema.get("type") != "object":
            logger.warning("Skipping MCP tool %s with an invalid input schema", tool.name)
            continue
        output_schema = tool.output_schema if valid_schema(tool.output_schema) else None
        description = re.sub(r"\s+", " ", tool.description or "").strip()[:MAX_DESCRIPTION]
        accepted[tool.name] = RemoteTool(tool.name, description, tool.input_schema, output_schema)
    return list(accepted.values())


def schema_errors(schema: dict[str, Any], value: Any) -> list[str]:
    """Field paths that fail validation. Never echoes the submitted values."""
    return sorted(
        "/".join(str(part) for part in error.absolute_path) or "(root)"
        for error in Draft202012Validator(schema).iter_errors(value)
    )
