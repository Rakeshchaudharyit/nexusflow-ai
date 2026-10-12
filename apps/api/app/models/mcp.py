import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import JSONDocument, string_enum
from app.models.identity import Timestamps


class McpTransport(StrEnum):
    # Only transports with a working client implementation belong here.
    STREAMABLE_HTTP = "streamable_http"


class McpServerStatus(StrEnum):
    """Last observed connectivity. Informational only; never used for authorization."""

    PENDING = "pending"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class McpServer(Timestamps, Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_mcp_servers_organization_slug"),
        UniqueConstraint("id", "organization_id", name="uq_mcp_servers_id_organization"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    transport: Mapped[McpTransport] = mapped_column(string_enum(McpTransport, "mcp_transport"))
    url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[McpServerStatus] = mapped_column(
        string_enum(McpServerStatus, "mcp_server_status"),
        default=McpServerStatus.PENDING,
        server_default=McpServerStatus.PENDING.value,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    last_error_message: Mapped[str | None] = mapped_column(String(500))


class McpTool(Timestamps, Base):
    """Discovered tool metadata. A cache of the last discovery, re-checked live on every call."""

    __tablename__ = "mcp_tools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["mcp_server_id", "organization_id"],
            ["mcp_servers.id", "mcp_servers.organization_id"],
            name="fk_mcp_tools_server_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("mcp_server_id", "name", name="uq_mcp_tools_server_name"),
        UniqueConstraint("id", "organization_id", name="uq_mcp_tools_id_organization"),
        Index("ix_mcp_tools_organization_name", "organization_id", "name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONDocument)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # False once the server stops listing the tool; kept for audit, never executable.
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
