"""Deterministic demo action proposals.

A proposal only names an action and its payload; it has no side effects and grants nothing.
Destructive wording is checked first so "delete" cannot hide behind other requested work.
"""

import re
from typing import Any

DELETE = re.compile(r"\b(?:delete|remove|purge|erase|wipe)\b", re.IGNORECASE)
EMAIL = re.compile(r"\be-?mail\b", re.IGNORECASE)
STAGE = re.compile(
    r"\bopportunity\s+stage\b|\bmove\b.*\bto\s+(?:proposal|negotiation)\b", re.IGNORECASE
)
NOTE = re.compile(r"\b(?:crm|internal)\s+note\b", re.IGNORECASE)
NOT_SENT = "Demonstration draft only. NexusFlow does not send email."


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "account"


def propose_action(objective: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return {"action_type", "payload"} for an objective that asks for an action, else None."""
    company = (result or {}).get("company") or "the account"
    summary = (result or {}).get("summary", "")
    if DELETE.search(objective):
        return {"action_type": "delete_record", "payload": {"company": company}}
    if EMAIL.search(objective):
        steps = (result or {}).get("recommended_next_steps", [])
        body = "\n".join([summary, "", "Proposed next steps:", *[f"- {s}" for s in steps]])
        return {
            "action_type": "send_followup_email",
            "payload": {
                "recipient": f"account-team@{slug(company)}.example",
                "subject": f"Next steps with {company}",
                "body": f"{body.strip()}\n\n{NOT_SENT}"[:5000],
            },
        }
    if STAGE.search(objective):
        return {
            "action_type": "update_opportunity_stage",
            "payload": {"company": company, "stage": "proposal"},
        }
    if NOTE.search(objective):
        return {
            "action_type": "create_crm_note",
            "payload": {"company": company, "note": (summary or "Opportunity reviewed.")[:2000]},
        }
    return None
