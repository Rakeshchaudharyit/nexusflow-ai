"""Server-built team configuration handed to the graph as runtime context.

Built from the database for one organization at run start. Nothing in it comes from the
objective text or agent instructions, so prompts cannot add members or grant tools.
"""

from dataclasses import dataclass, field
from uuid import UUID

from app.models.teams import SPECIALIST_ROLES, TeamRole

# Execution order of specialist roles; the supervisor plans only roles the team has.
ROLE_ORDER = (*SPECIALIST_ROLES, TeamRole.WRITER, TeamRole.VALIDATOR)


@dataclass(frozen=True)
class MemberConfig:
    member_id: UUID
    agent_id: UUID
    agent_name: str
    role: TeamRole
    is_required: bool
    instructions: str
    tool_keys: tuple[str, ...] = ()
    # M9: knowledge sources this member's agent may search (needs internal:knowledge_search).
    knowledge_source_ids: tuple[UUID, ...] = ()

    def describe(self) -> dict:
        """What the supervisor may know about a member: no tenant identifiers or tools."""
        return {"role": self.role.value, "agent_name": self.agent_name}


@dataclass(frozen=True)
class TeamConfig:
    team_id: UUID
    name: str
    members: tuple[MemberConfig, ...] = field(default_factory=tuple)

    def member(self, role: TeamRole | str) -> MemberConfig | None:
        return next((member for member in self.members if member.role == role), None)

    @property
    def supervisor(self) -> MemberConfig:
        supervisor = self.member(TeamRole.SUPERVISOR)
        if supervisor is None:
            raise ValueError("Team configuration has no supervisor")
        return supervisor

    @property
    def roster(self) -> list[dict]:
        return [
            member.describe() for role in ROLE_ORDER if (member := self.member(role)) is not None
        ]


def team_problems(roles: list[TeamRole], inactive_agents: list[str]) -> list[str]:
    """Why a team with these member roles cannot be active; empty when it can."""
    problems = []
    if roles.count(TeamRole.SUPERVISOR) != 1:
        problems.append("exactly one supervisor is required")
    if not any(role in SPECIALIST_ROLES for role in roles):
        problems.append("at least one specialist (customer specialist, researcher or analyst)")
    for role in (TeamRole.WRITER, TeamRole.VALIDATOR):
        if role not in roles:
            problems.append(f"a {role.value} is required")
    if inactive_agents:
        problems.append(f"member agents must be active: {', '.join(sorted(inactive_agents))}")
    return problems
