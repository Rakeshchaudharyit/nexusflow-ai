from app.agents.errors import AgentRuntimeError


class TeamExecutionError(AgentRuntimeError):
    code = "team_execution_failed"
    message = "The team run could not be completed."
