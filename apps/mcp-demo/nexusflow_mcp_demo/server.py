"""NexusFlow demonstration MCP server.

Exposes exactly three side-effect-free tools. There are deliberately no filesystem, shell,
network, environment or database capabilities.
"""

import operator
from decimal import Decimal, InvalidOperation, localcontext
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from nexusflow_mcp_demo.data import DEMO_CUSTOMERS, SOURCE, find_customer

SERVICE = "nexusflow-demo-mcp"
VERSION = "0.4.0"
OPERATIONS = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
}
Number = Annotated[float, Field(ge=-(10**12), le=10**12, allow_inf_nan=False)]


class CustomerResult(BaseModel):
    found: bool
    company: str | None = None
    segment: str | None = None
    status: str | None = None
    account_owner: str | None = None
    region: str | None = None
    available: list[str] = []
    source: str = SOURCE


class CalculationResult(BaseModel):
    operation: Literal["add", "subtract", "multiply", "divide"]
    a: str
    b: str
    result: str


class PlatformInfo(BaseModel):
    service: str
    status: Literal["ok"]
    protocol: Literal["MCP"]
    transport: Literal["streamable_http"]
    version: str
    tools: list[str]
    data_notice: str


def format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(value.quantize(Decimal(1)))
    return format(value.quantize(Decimal("1e-10")).normalize(), "f")


def build_server() -> MCPServer:
    server = MCPServer(
        SERVICE,
        title="NexusFlow Demo Tools",
        description="Demonstration MCP server for NexusFlow. All data is synthetic.",
        version=VERSION,
    )

    @server.tool()
    def search_customer(
        company: Annotated[str, Field(min_length=1, max_length=200)],
    ) -> CustomerResult:
        """Look up a company in the NexusFlow demonstration customer dataset."""
        record = find_customer(company)
        if record is None:
            return CustomerResult(found=False, available=[r["company"] for r in DEMO_CUSTOMERS])
        fields = {key: value for key, value in record.items() if key != "aliases"}
        return CustomerResult(found=True, **fields)

    @server.tool()
    def calculate(
        operation: Literal["add", "subtract", "multiply", "divide"], a: Number, b: Number
    ) -> CalculationResult:
        """Apply one arithmetic operation to two numbers. No expression evaluation."""
        left, right = Decimal(str(a)), Decimal(str(b))
        if operation == "divide" and right == 0:
            raise ToolError("Division by zero is not allowed.")
        with localcontext() as context:
            context.prec = 28
            try:
                result = OPERATIONS[operation](left, right)
            except InvalidOperation as error:
                raise ToolError("The calculation could not be performed.") from error
        return CalculationResult(
            operation=operation,
            a=format_decimal(left),
            b=format_decimal(right),
            result=format_decimal(result),
        )

    @server.tool()
    def get_platform_info() -> PlatformInfo:
        """Describe this demonstration MCP service. Reveals no host or environment details."""
        return PlatformInfo(
            service=SERVICE,
            status="ok",
            protocol="MCP",
            transport="streamable_http",
            version=VERSION,
            tools=["search_customer", "calculate", "get_platform_info"],
            data_notice=SOURCE,
        )

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": SERVICE})

    return server


def create_app(allowed_hosts: list[str]) -> Starlette:
    """Stateless JSON streamable HTTP app; Host headers outside `allowed_hosts` are rejected."""
    return build_server().streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=64 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts, allowed_origins=[]
        ),
    )
