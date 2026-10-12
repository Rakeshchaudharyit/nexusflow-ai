import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActionType(StrEnum):
    CREATE_CRM_NOTE = "create_crm_note"
    SEND_FOLLOWUP_EMAIL = "send_followup_email"
    UPDATE_OPPORTUNITY_STAGE = "update_opportunity_stage"


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CRMNote(Payload):
    company: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=2000)


class FollowupEmail(Payload):
    recipient: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("recipient")
    @classmethod
    def demo_address(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.example", value):
            raise ValueError("Demo email recipients must use a .example domain")
        return value


class OpportunityStage(Payload):
    company: str = Field(min_length=1, max_length=120)
    stage: Literal["qualified", "proposal", "negotiation", "won", "lost"]


SCHEMAS = {
    ActionType.CREATE_CRM_NOTE: CRMNote,
    ActionType.SEND_FOLLOWUP_EMAIL: FollowupEmail,
    ActionType.UPDATE_OPPORTUNITY_STAGE: OpportunityStage,
}


def validate_payload(action_type: str, payload: dict) -> dict:
    return SCHEMAS[ActionType(action_type)].model_validate(payload).model_dump(mode="json")
