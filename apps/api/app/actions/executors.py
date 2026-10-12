"""Deterministic local simulations of business actions.

Nothing leaves the process: no email, CRM or network call. Every result says so explicitly.
"""

from typing import Any

from app.actions.schemas import validate_payload

MESSAGES = {
    "create_crm_note": "Simulated: the CRM note was recorded in NexusFlow only. No CRM was called.",
    "send_followup_email": (
        "Simulated: the follow-up email was recorded in NexusFlow only. No email was sent."
    ),
    "update_opportunity_stage": (
        "Simulated: the stage change was recorded in NexusFlow only. No CRM was updated."
    ),
}


def simulate(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    clean = validate_payload(action_type, payload)
    return {
        "simulated": True,
        "action_type": action_type,
        "message": MESSAGES[action_type],
        "record": clean,
    }
