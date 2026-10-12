class AgentRuntimeError(Exception):
    """Failure whose code and message are safe to persist and return to clients.

    Anything else raised during execution is treated as an internal fault and replaced with
    a generic message before it leaves the runtime.
    """

    code = "agent_execution_failed"
    message = "The agent run could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, str | int | None] | None = None,
    ):
        self.code = code or self.code
        self.message = message or self.message
        # Safe, JSON-serializable context (e.g. which tool failed); persisted with the event.
        self.details = details or {}
        super().__init__(self.message)


class AgentExecutionError(AgentRuntimeError):
    pass


class ToolExecutionError(AgentRuntimeError):
    code = "tool_execution_failed"
    message = "A tool failed while executing the agent run."
