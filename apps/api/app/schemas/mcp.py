from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.mcp import McpServerStatus, McpTransport


class McpServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    transport: Literal["streamable_http"] = "streamable_http"
    url: str = Field(min_length=1, max_length=2048)


class McpServerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    is_enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_values(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class McpServerResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str
    transport: McpTransport
    url: str
    status: McpServerStatus
    is_enabled: bool
    tool_count: int
    created_by_user_id: UUID
    last_connected_at: datetime | None
    last_discovered_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime


class McpToolResponse(BaseModel):
    id: UUID
    mcp_server_id: UUID
    name: str
    tool_key: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    is_enabled: bool
    is_available: bool
    discovered_at: datetime


class McpToolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool


class McpConnectionError(BaseModel):
    code: str
    message: str


class McpConnectionTest(BaseModel):
    status: Literal["connected", "unavailable"]
    server: str | None
    version: str | None
    protocol_version: str | None
    duration_ms: int
    error: McpConnectionError | None


class McpDiscoveryResponse(BaseModel):
    server: McpServerResponse
    tools: list[McpToolResponse]
    added: list[str]
    updated: list[str]
    removed: list[str]
