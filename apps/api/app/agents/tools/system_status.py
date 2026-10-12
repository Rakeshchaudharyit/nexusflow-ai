from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from app.agents.tools.base import ToolDefinition, ToolExecutionContext
from app.schemas.health import ReadinessResponse


class SystemStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemStatusTool:
    """Reports live platform readiness using the same probe as /health/ready."""

    definition = ToolDefinition(
        name="system_status",
        description="Report API, PostgreSQL and Redis readiness.",
        input_model=SystemStatusInput,
    )

    def __init__(self, probe: Callable[[], ReadinessResponse]):
        self._probe = probe

    def execute(self, arguments: SystemStatusInput, context: ToolExecutionContext) -> dict:
        readiness = self._probe()
        return {"status": readiness.status, "services": readiness.services.model_dump()}
