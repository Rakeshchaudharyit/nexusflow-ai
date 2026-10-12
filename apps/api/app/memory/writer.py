"""Memory writes from runs and approvals, and the deterministic thread summary.

Write policy: only explicit facts, validated results, approved decisions and manual entries.
Never tool errors, stack traces, raw prompts, routing instructions or full action payloads.

Every write has an idempotency key, so a retried or replayed run upserts the same rows instead
of adding new ones; writers lock the thread row, so concurrent runs in one thread serialise.
Writes happen inside the caller's (worker's) transaction that completes the run.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.events import EventStream
from app.core.config import Settings
from app.memory.context import clean
from app.models.agents import RunEventStatus, RunEventType
from app.models.memory import (
    MemoryEntry,
    MemoryScope,
    MemorySource,
    MemoryThread,
    MemoryType,
)

SUMMARY_SECTIONS = ("Facts", "Results", "Decisions", "Preferences and notes", "Open questions")


@dataclass
class WriteLog:
    saved: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)

    def record(self, events: EventStream | None, db: Session) -> None:
        """One business event per run, not one per memory: the timeline stays readable."""
        if events is None or not (self.saved or self.updated):
            return
        events.append(
            db,
            RunEventType.MEMORY_SAVED if self.saved else RunEventType.MEMORY_UPDATED,
            RunEventStatus.COMPLETED,
            node="memory_writer",
            output_payload={"saved": self.saved, "updated": self.updated},
        )


class MemoryWriter:
    def __init__(self, db: Session, settings: Settings, organization_id: UUID):
        self.db = db
        self.settings = settings
        self.organization_id = organization_id
        self.log = WriteLog()

    def _expiry(self) -> datetime | None:
        days = self.settings.memory_default_ttl_days
        return datetime.now(UTC) + timedelta(days=days) if days else None

    def lock_thread(self, thread_id: UUID) -> MemoryThread | None:
        return self.db.scalar(
            select(MemoryThread)
            .where(
                MemoryThread.id == thread_id,
                MemoryThread.organization_id == self.organization_id,
            )
            .with_for_update()
        )

    def _upsert(self, key: str, label: str, **values: Any) -> MemoryEntry:
        entry = self.db.scalar(
            select(MemoryEntry).where(
                MemoryEntry.organization_id == self.organization_id,
                MemoryEntry.idempotency_key == key,
            )
        )
        if entry is None:
            entry = MemoryEntry(organization_id=self.organization_id, idempotency_key=key, **values)
            self.db.add(entry)
            self.db.flush()
            self.log.saved.append(label)
            return entry
        changed = any(
            getattr(entry, name) != value
            for name, value in values.items()
            if name not in ("expires_at",)
        )
        if changed or not entry.is_active:
            for name, value in values.items():
                setattr(entry, name, value)
            entry.is_active, entry.deactivated_at = True, None
            self.db.flush()
            self.log.updated.append(label)
        return entry

    def fact(
        self,
        thread_id: UUID,
        key: str,
        value: Any,
        *,
        source: MemorySource,
        source_id: UUID,
        user_id: UUID | None,
        confidence: float = 1.0,
        team_id: UUID | None = None,
    ) -> None:
        """A thread fact keyed by name: a later run updates it rather than duplicating it."""
        text = clean(str(value), 500)
        if not text:
            return
        self._upsert(
            f"thread:{thread_id}:fact:{key}",
            key,
            memory_type=MemoryType.FACT,
            scope=MemoryScope.THREAD,
            thread_id=thread_id,
            team_id=team_id,
            fact_key=key,
            fact_value=text,
            confidence=confidence,
            content=f"{key}: {text}",
            importance=4,
            source_type=source,
            source_id=source_id,
            created_by_user_id=user_id,
            expires_at=self._expiry(),
        )

    def note(
        self,
        thread_id: UUID,
        slot: str,
        content: str,
        *,
        source: MemorySource,
        source_id: UUID,
        user_id: UUID | None,
        importance: int = 3,
        team_id: UUID | None = None,
    ) -> None:
        self._upsert(
            f"{source.value}:{source_id}:{slot}",
            slot,
            memory_type=MemoryType.THREAD,
            scope=MemoryScope.THREAD,
            thread_id=thread_id,
            team_id=team_id,
            content=clean(content, 2000),
            summary=clean(content, 300),
            importance=importance,
            source_type=source,
            source_id=source_id,
            created_by_user_id=user_id,
            expires_at=self._expiry(),
        )

    def refresh_summary(self, thread_id: UUID) -> None:
        """Deterministic rolling summary once the thread reaches MEMORY_SUMMARY_THRESHOLD."""
        active = list(
            self.db.scalars(
                select(MemoryEntry)
                .where(
                    MemoryEntry.organization_id == self.organization_id,
                    MemoryEntry.thread_id == thread_id,
                    MemoryEntry.is_active.is_(True),
                    MemoryEntry.memory_type != MemoryType.SUMMARY,
                )
                .order_by(MemoryEntry.created_at, MemoryEntry.id)
            )
        )
        if len(active) < self.settings.memory_summary_threshold:
            return
        content = summarize(active)
        self._upsert(
            f"thread:{thread_id}:summary",
            "thread_summary",
            memory_type=MemoryType.SUMMARY,
            scope=MemoryScope.THREAD,
            thread_id=thread_id,
            content=content,
            summary=clean(content, 300),
            importance=5,
            source_type=MemorySource.THREAD_SUMMARY,
            source_id=thread_id,
            created_by_user_id=None,
            expires_at=None,
        )

    def touch(self, thread: MemoryThread) -> None:
        thread.last_activity_at = func.now()


def summarize(entries: list[MemoryEntry]) -> str:
    """Pure function of the thread's memory, so tests and retries get identical summaries.
    It reads only stored memory (already free of payloads and secrets)."""
    facts = sorted(
        {e.fact_key: e.fact_value for e in entries if e.fact_key}.items(), key=lambda kv: kv[0]
    )
    results = [
        e.summary or e.content
        for e in entries
        if e.source_type == MemorySource.TEAM_RUN and not e.fact_key
    ]
    decisions = [
        e.summary or e.content for e in entries if e.source_type == MemorySource.APPROVED_ACTION
    ]
    notes = [
        e.summary or e.content
        for e in entries
        if e.source_type in (MemorySource.MANUAL, MemorySource.USER_INPUT) and not e.fact_key
    ]
    sections = [
        ("Facts", "; ".join(f"{key}={value}" for key, value in facts) or "none recorded"),
        ("Results", " | ".join(results[-3:]) or "none recorded"),
        ("Decisions", " | ".join(decisions[-3:]) or "none recorded"),
        ("Preferences and notes", " | ".join(notes[-3:]) or "none recorded"),
        ("Open questions", "none recorded"),
    ]
    return clean(" ".join(f"{title}: {body}." for title, body in sections), 2000)


def customer_record(state: dict) -> dict | None:
    """The validated customer record from a successful lookup, internal or MCP."""
    for record in state.get("tool_results", []):
        output = record.get("output") or {}
        customer = output.get("customer", output) if output.get("found") else None
        if customer and customer.get("company"):
            return customer
    return None


def remember_agent_result(
    db: Session,
    settings: Settings,
    events: EventStream,
    *,
    organization_id: UUID,
    thread_id: UUID,
    run_id: UUID,
    user_id: UUID,
    state: dict,
) -> None:
    """After a completed single-agent run in a thread: keep the structured customer facts.
    Calculations and status checks are transient and are not remembered."""
    customer = customer_record(state) if state.get("intent") == "customer_lookup" else None
    if customer is None:
        return
    writer = MemoryWriter(db, settings, organization_id)
    thread = writer.lock_thread(thread_id)
    if thread is None:
        return
    for key, field_name in (
        ("company_name", "company"),
        ("segment", "segment"),
        ("region", "region"),
        ("account_owner", "account_owner"),
        ("customer_status", "status"),
    ):
        if customer.get(field_name):
            writer.fact(
                thread_id,
                key,
                str(customer[field_name]).replace("_", " "),
                source=MemorySource.AGENT_RUN,
                source_id=run_id,
                user_id=user_id,
            )
    writer.refresh_summary(thread_id)
    writer.touch(thread)
    writer.log.record(events, db)


def remember_team_result(
    db: Session,
    settings: Settings,
    events: EventStream,
    *,
    organization_id: UUID,
    thread_id: UUID,
    team_id: UUID,
    run_id: UUID,
    user_id: UUID,
    state: dict,
) -> None:
    """After a validated team result in a thread: score, customer facts and one assessment note.
    Supervisor routing, handoff tasks and revision feedback are deliberately not stored."""
    output = state.get("final_output") or {}
    validation = output.get("validation") or {}
    if not output.get("company") or not validation.get("valid"):
        return
    writer = MemoryWriter(db, settings, organization_id)
    thread = writer.lock_thread(thread_id)
    if thread is None:
        return
    confidence = float(validation.get("confidence") or 1.0)
    facts = {"company_name": output["company"], "opportunity_score": output["opportunity_score"]}
    draft_facts = (state.get("draft_output") or {}).get("facts") or {}
    for key, field_name in (
        ("segment", "segment"),
        ("account_owner", "account_owner"),
        ("customer_status", "status"),
    ):
        if draft_facts.get(field_name):
            facts[key] = str(draft_facts[field_name]).replace("_", " ")
    for key, value in facts.items():
        writer.fact(
            thread_id,
            key,
            value,
            source=MemorySource.TEAM_RUN,
            source_id=run_id,
            user_id=user_id,
            confidence=confidence,
            team_id=team_id,
        )
    writer.note(
        thread_id,
        "assessment",
        (
            f"Team assessment: {output['company']} scored {output['opportunity_score']}/100, "
            f"validated (confidence {round(confidence * 100)}%). "
            f"Strengths: {'; '.join(output.get('strengths', [])[:3])}. "
            f"Risks: {'; '.join(output.get('risks', [])[:3])}. "
            f"Next steps: {'; '.join(output.get('recommended_next_steps', [])[:3])}."
        ),
        source=MemorySource.TEAM_RUN,
        source_id=run_id,
        user_id=user_id,
        importance=4,
        team_id=team_id,
    )
    writer.refresh_summary(thread_id)
    writer.touch(thread)
    writer.log.record(events, db)


def remember_approval(
    db: Session,
    settings: Settings,
    events: EventStream,
    *,
    organization_id: UUID,
    thread_id: UUID,
    team_id: UUID,
    approval_id: UUID,
    action_type: str,
    reviewer_id: UUID | None,
    decided_at: datetime | None,
) -> None:
    """An executed approval leaves a short audit summary: what, when, simulated. Never the
    payload (recipient, subject or body)."""
    writer = MemoryWriter(db, settings, organization_id)
    thread = writer.lock_thread(thread_id)
    if thread is None:
        return
    when = (decided_at or datetime.now(UTC)).date().isoformat()
    writer.note(
        thread_id,
        "decision",
        f"Approved action {action_type.replace('_', ' ')} on {when}; executed as a simulation "
        "(nothing was sent or changed externally).",
        source=MemorySource.APPROVED_ACTION,
        source_id=approval_id,
        user_id=reviewer_id,
        importance=3,
        team_id=team_id,
    )
    writer.refresh_summary(thread_id)
    writer.touch(thread)
    writer.log.record(events, db)
