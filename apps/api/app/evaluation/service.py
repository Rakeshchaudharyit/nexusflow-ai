"""Evaluation APIs. Every query is scoped to the caller's organization; another
organization's datasets, cases, runs and results are indistinguishable from missing ones."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import APIError
from app.evaluation.demo import demo_cases
from app.jobs.service import JobQueue, create_job, deliver
from app.models.agents import Agent, AgentStatus
from app.models.evaluation import (
    CaseTarget,
    DatasetStatus,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    EvaluationRunStatus,
)
from app.models.identity import User
from app.models.jobs import ACTIVE_JOB_STATUSES, ExecutionJob, JobStatus, JobType
from app.models.knowledge import AgentKnowledgeSource
from app.models.observability import RunTrace
from app.models.teams import AgentTeam, AgentTool
from app.schemas.agents import AgentCreate
from app.schemas.evaluation import (
    CaseChange,
    CaseInput,
    CaseResponse,
    CaseUpdate,
    DatasetCreate,
    DatasetDetail,
    DatasetResponse,
    DatasetUpdate,
    EvaluationComparison,
    EvaluationRunDetail,
    EvaluationRunSummary,
    ResultResponse,
)
from app.services.agent_teams import get_team
from app.services.agents import create_agent, get_agent

EXPECTATION_FIELDS = (
    "expected_status",
    "expected_intent",
    "expected_tool_key",
    "expected_output_contains",
    "expected_output_excludes",
    "expected_values",
    "expected_citation_documents",
    "expected_no_match",
    "expected_policy_decision",
    "expected_action_type",
    "retrieval_k",
)


# --- datasets and cases ------------------------------------------------------------------------


def get_dataset(db: Session, organization_id: UUID, dataset_id: UUID) -> EvaluationDataset:
    dataset = db.scalar(
        select(EvaluationDataset).where(
            EvaluationDataset.id == dataset_id,
            EvaluationDataset.organization_id == organization_id,
        )
    )
    if dataset is None:
        raise APIError(404, "dataset_not_found", "Evaluation dataset not found.")
    return dataset


def _check_targets(db: Session, organization_id: UUID, case: CaseInput | CaseUpdate) -> None:
    if case.target_agent_id:
        get_agent(db, organization_id, case.target_agent_id)  # 404 across tenants
    if case.target_team_id:
        get_team(db, organization_id, case.target_team_id)


def _add_case(db: Session, dataset: EvaluationDataset, data: CaseInput, position: int):
    _check_targets(db, dataset.organization_id, data)
    values = data.model_dump(exclude={"position"})
    case = EvaluationCase(
        organization_id=dataset.organization_id,
        dataset_id=dataset.id,
        position=data.position if data.position is not None else position,
        metadata_json={},
        **values,
    )
    db.add(case)
    return case


def _next_position(db: Session, dataset: EvaluationDataset) -> int:
    return (
        db.scalar(
            select(func.coalesce(func.max(EvaluationCase.position), -1)).where(
                EvaluationCase.dataset_id == dataset.id
            )
        )
        + 1
    )


def create_dataset(
    db: Session, organization_id: UUID, user: User, data: DatasetCreate
) -> DatasetDetail:
    dataset = EvaluationDataset(
        organization_id=organization_id,
        name=data.name,
        description=data.description,
        dataset_type=data.dataset_type,
        created_by_user_id=user.id,
    )
    db.add(dataset)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise APIError(409, "dataset_exists", "A dataset with this name exists.") from error
    for position, case in enumerate(data.cases):
        _add_case(db, dataset, case, position)
    db.commit()
    return dataset_detail(db, organization_id, dataset.id)


MEMORY_AGENT_NAME = "Evaluation · Memory-only Agent"


def ensure_memory_agent(db: Session, organization_id: UUID, user: User) -> Agent:
    """The demo's memory-only agent: active, no enabled tools, no enabled knowledge sources.
    Reused when it already exists; refused (not silently "fixed") if someone granted it
    tools or knowledge, since the memory case would then no longer test memory in isolation."""
    agent = db.scalar(
        select(Agent)
        .where(Agent.organization_id == organization_id, Agent.name == MEMORY_AGENT_NAME)
        .order_by(Agent.created_at)
        .limit(1)
    )
    if agent is None:
        agent = create_agent(
            db,
            organization_id,
            user,
            AgentCreate(
                name=MEMORY_AGENT_NAME,
                description="Evaluation fixture: answers only from thread memory.",
                instructions=(
                    "Answer account questions from remembered thread facts only. "
                    "No tools or knowledge sources are assigned."
                ),
            ),
        )
    tools = db.scalar(
        select(func.count())
        .select_from(AgentTool)
        .where(
            AgentTool.organization_id == organization_id,
            AgentTool.agent_id == agent.id,
            AgentTool.is_enabled.is_(True),
        )
    )
    sources = db.scalar(
        select(func.count())
        .select_from(AgentKnowledgeSource)
        .where(
            AgentKnowledgeSource.organization_id == organization_id,
            AgentKnowledgeSource.agent_id == agent.id,
            AgentKnowledgeSource.is_enabled.is_(True),
        )
    )
    if tools or sources:
        raise APIError(
            409,
            "memory_agent_not_isolated",
            f"'{MEMORY_AGENT_NAME}' has tools or knowledge sources enabled; remove them so the "
            "memory recall case tests memory alone.",
        )
    if agent.status == AgentStatus.ARCHIVED:
        raise APIError(409, "memory_agent_archived", f"'{MEMORY_AGENT_NAME}' is archived.")
    if agent.status != AgentStatus.ACTIVE:
        agent.status = AgentStatus.ACTIVE
        db.commit()
    return agent


def create_demo_dataset(
    db: Session, organization_id: UUID, user: User, name: str, knowledge_agent_id: UUID | None
) -> DatasetDetail:
    if knowledge_agent_id:
        get_agent(db, organization_id, knowledge_agent_id)
    memory_agent = ensure_memory_agent(db, organization_id, user)
    return create_dataset(
        db,
        organization_id,
        user,
        DatasetCreate(
            name=name,
            description=(
                "Deterministic regression checks: tools, MCP, memory recall, team analysis, "
                "approval, policy deny, adversarial memory"
                + (", RAG citation and no-match." if knowledge_agent_id else ".")
            ),
            dataset_type="mixed",
            cases=demo_cases(knowledge_agent_id, memory_agent.id),
        ),
    )


def _counts(db: Session, organization_id: UUID, dataset_ids: list[UUID]):
    cases = dict(
        db.execute(
            select(EvaluationCase.dataset_id, func.count())
            .where(
                EvaluationCase.organization_id == organization_id,
                EvaluationCase.dataset_id.in_(dataset_ids),
            )
            .group_by(EvaluationCase.dataset_id)
        ).all()
    )
    runs = dict(
        db.execute(
            select(EvaluationRun.dataset_id, func.count())
            .where(
                EvaluationRun.organization_id == organization_id,
                EvaluationRun.dataset_id.in_(dataset_ids),
            )
            .group_by(EvaluationRun.dataset_id)
        ).all()
    )
    return cases, runs


def list_datasets(db: Session, organization_id: UUID) -> list[DatasetResponse]:
    datasets = list(
        db.scalars(
            select(EvaluationDataset)
            .where(EvaluationDataset.organization_id == organization_id)
            .order_by(EvaluationDataset.updated_at.desc())
        )
    )
    cases, runs = _counts(db, organization_id, [d.id for d in datasets])
    responses = []
    for dataset in datasets:
        latest = db.scalar(
            select(EvaluationRun)
            .where(
                EvaluationRun.dataset_id == dataset.id,
                EvaluationRun.organization_id == organization_id,
            )
            .order_by(EvaluationRun.created_at.desc())
            .limit(1)
        )
        response = DatasetResponse.model_validate(dataset)
        response.case_count = cases.get(dataset.id, 0)
        response.run_count = runs.get(dataset.id, 0)
        response.last_run = run_summary(db, latest) if latest else None
        responses.append(response)
    return responses


def dataset_detail(db: Session, organization_id: UUID, dataset_id: UUID) -> DatasetDetail:
    dataset = get_dataset(db, organization_id, dataset_id)
    cases = list(
        db.scalars(
            select(EvaluationCase)
            .where(
                EvaluationCase.dataset_id == dataset.id,
                EvaluationCase.organization_id == organization_id,
            )
            .order_by(EvaluationCase.position, EvaluationCase.created_at)
        )
    )
    runs = list(
        db.scalars(
            select(EvaluationRun)
            .where(
                EvaluationRun.dataset_id == dataset.id,
                EvaluationRun.organization_id == organization_id,
            )
            .order_by(EvaluationRun.created_at.desc())
            .limit(20)
        )
    )
    base = DatasetResponse.model_validate(dataset)
    return DatasetDetail(
        **{**base.model_dump(), "case_count": len(cases), "run_count": len(runs)},
        cases=[CaseResponse.model_validate(case) for case in cases],
        runs=[run_summary(db, run) for run in runs],
    )


def update_dataset(
    db: Session, organization_id: UUID, dataset_id: UUID, data: DatasetUpdate
) -> DatasetDetail:
    dataset = get_dataset(db, organization_id, dataset_id)
    for field in ("name", "description", "status"):
        value = getattr(data, field)
        if value is not None:
            setattr(dataset, field, value)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(409, "dataset_exists", "A dataset with this name exists.") from error
    return dataset_detail(db, organization_id, dataset_id)


def _no_active_runs(db: Session, organization_id: UUID, dataset_id: UUID) -> None:
    active = db.scalar(
        select(func.count())
        .select_from(EvaluationRun)
        .where(
            EvaluationRun.dataset_id == dataset_id,
            EvaluationRun.organization_id == organization_id,
            EvaluationRun.status.in_((EvaluationRunStatus.QUEUED, EvaluationRunStatus.RUNNING)),
        )
    )
    if active:
        raise APIError(
            409, "evaluation_in_progress", "Wait for the running evaluation to finish first."
        )


def delete_dataset(db: Session, organization_id: UUID, dataset_id: UUID) -> None:
    """Cascades cases, evaluation runs, results and the runs/threads evaluations created."""
    dataset = get_dataset(db, organization_id, dataset_id)
    _no_active_runs(db, organization_id, dataset.id)
    db.delete(dataset)
    db.commit()


def add_case(db: Session, organization_id: UUID, dataset_id: UUID, data: CaseInput):
    dataset = get_dataset(db, organization_id, dataset_id)
    _no_active_runs(db, organization_id, dataset.id)
    case = _add_case(db, dataset, data, _next_position(db, dataset))
    dataset.updated_at = datetime.now(UTC)
    db.commit()
    return CaseResponse.model_validate(case)


def get_case(db: Session, organization_id: UUID, case_id: UUID) -> EvaluationCase:
    case = db.scalar(
        select(EvaluationCase).where(
            EvaluationCase.id == case_id, EvaluationCase.organization_id == organization_id
        )
    )
    if case is None:
        raise APIError(404, "case_not_found", "Evaluation case not found.")
    return case


def update_case(db: Session, organization_id: UUID, case_id: UUID, data: CaseUpdate):
    case = get_case(db, organization_id, case_id)
    _no_active_runs(db, organization_id, case.dataset_id)
    _check_targets(db, organization_id, data)
    for field in data.model_fields_set:
        setattr(case, field, getattr(data, field))
    if case.target_kind == CaseTarget.AGENT and case.target_team_id:
        raise APIError(422, "invalid_case", "Agent cases cannot target a team.")
    if case.target_kind == CaseTarget.TEAM and case.target_agent_id:
        raise APIError(422, "invalid_case", "Team cases cannot target an agent.")
    db.commit()
    return CaseResponse.model_validate(case)


def delete_case(db: Session, organization_id: UUID, case_id: UUID) -> None:
    case = get_case(db, organization_id, case_id)
    _no_active_runs(db, organization_id, case.dataset_id)
    db.delete(case)
    db.commit()


# --- evaluation runs ---------------------------------------------------------------------------


def _names(db: Session, organization_id: UUID, run: EvaluationRun) -> list[str]:
    names = []
    if run.target_agent_id:
        names.append(
            db.scalar(
                select(Agent.name).where(
                    Agent.id == run.target_agent_id, Agent.organization_id == organization_id
                )
            )
            or "agent"
        )
    if run.target_team_id:
        names.append(
            db.scalar(
                select(AgentTeam.name).where(
                    AgentTeam.id == run.target_team_id,
                    AgentTeam.organization_id == organization_id,
                )
            )
            or "team"
        )
    return names


def run_summary(db: Session, run: EvaluationRun, results=None) -> EvaluationRunSummary:
    if results is None:
        results = list(
            db.scalars(
                select(EvaluationResult).where(
                    EvaluationResult.evaluation_run_id == run.id,
                    EvaluationResult.organization_id == run.organization_id,
                )
            )
        )
    retrieval = [
        (item.actual_json or {}).get("retrieval")
        for item in results
        if (item.actual_json or {}).get("retrieval")
    ]
    finished = run.passed_count + run.failed_count + run.error_count
    return EvaluationRunSummary(
        id=run.id,
        dataset_id=run.dataset_id,
        dataset_name=db.scalar(
            select(EvaluationDataset.name).where(EvaluationDataset.id == run.dataset_id)
        ),
        status=run.status,
        target_type=run.target_type,
        target_agent_id=run.target_agent_id,
        target_team_id=run.target_team_id,
        target_names=_names(db, run.organization_id, run),
        config_hash=run.config_hash,
        is_baseline=run.is_baseline,
        case_count=run.case_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        error_count=run.error_count,
        pass_rate=round(run.passed_count / finished, 4) if finished else None,
        score=run.score,
        duration_ms=run.duration_ms,
        retrieval_hit_rate=(
            round(sum(1 for item in retrieval if item.get("hit_at_k")) / len(retrieval), 4)
            if retrieval
            else None
        ),
        retrieval_mrr=(
            round(sum(item.get("reciprocal_rank", 0) for item in retrieval) / len(retrieval), 4)
            if retrieval
            else None
        ),
        error_code=run.error_code,
        error_message=run.error_message,
        created_by_user_id=run.created_by_user_id,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def start_run(
    db: Session,
    settings: Settings,
    queue: JobQueue,
    organization_id: UUID,
    user: User,
    dataset_id: UUID,
    target_agent_id: UUID | None,
    target_team_id: UUID | None,
) -> EvaluationRunSummary:
    """Persist the evaluation run and its job, enqueue, and return immediately (queued)."""
    dataset = get_dataset(db, organization_id, dataset_id)
    if dataset.status != DatasetStatus.ACTIVE:
        raise APIError(409, "dataset_archived", "Archived datasets cannot be run.")
    if target_agent_id:
        get_agent(db, organization_id, target_agent_id)
    if target_team_id:
        get_team(db, organization_id, target_team_id)
    case_count = db.scalar(
        select(func.count())
        .select_from(EvaluationCase)
        .where(EvaluationCase.dataset_id == dataset.id)
    )
    if not case_count:
        raise APIError(409, "dataset_empty", "Add at least one case before running.")
    run = EvaluationRun(
        organization_id=organization_id,
        dataset_id=dataset.id,
        target_type=(
            "mixed" if target_agent_id and target_team_id else "team" if target_team_id else "agent"
        ),
        target_agent_id=target_agent_id,
        target_team_id=target_team_id,
        target_snapshot={},
        case_count=case_count,
        created_by_user_id=user.id,
    )
    db.add(run)
    db.flush()
    job = create_job(
        db,
        settings,
        organization_id=organization_id,
        job_type=JobType.EVALUATION_RUN,
        evaluation_run_id=run.id,
    )
    db.commit()
    deliver(db, queue, job.id)
    db.expire_all()  # an inline queue may already have executed it
    return run_summary(db, db.get(EvaluationRun, run.id))


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> EvaluationRun:
    run = db.scalar(
        select(EvaluationRun).where(
            EvaluationRun.id == run_id, EvaluationRun.organization_id == organization_id
        )
    )
    if run is None:
        raise APIError(404, "evaluation_run_not_found", "Evaluation run not found.")
    return run


def list_runs(
    db: Session,
    organization_id: UUID,
    dataset_id: UUID | None,
    status: EvaluationRunStatus | None,
    limit: int,
) -> list[EvaluationRunSummary]:
    query = select(EvaluationRun).where(EvaluationRun.organization_id == organization_id)
    if dataset_id:
        query = query.where(EvaluationRun.dataset_id == dataset_id)
    if status:
        query = query.where(EvaluationRun.status == status)
    runs = db.scalars(query.order_by(EvaluationRun.created_at.desc()).limit(limit))
    return [run_summary(db, run) for run in runs]


def _expected(case: EvaluationCase) -> dict:
    expected = {}
    for field in EXPECTATION_FIELDS:
        value = getattr(case, field)
        if value not in (None, [], {}, False) and not (field == "retrieval_k" and value == 5):
            expected[field.removeprefix("expected_")] = value
    if case.setup_inputs:
        expected["setup_inputs"] = case.setup_inputs
    if case.setup_memory:
        expected["setup_memory"] = case.setup_memory
    return expected


def run_detail(db: Session, organization_id: UUID, run_id: UUID) -> EvaluationRunDetail:
    run = get_run(db, organization_id, run_id)
    rows = db.execute(
        select(EvaluationResult, EvaluationCase)
        .join(
            EvaluationCase,
            (EvaluationCase.id == EvaluationResult.case_id)
            & (EvaluationCase.organization_id == EvaluationResult.organization_id),
        )
        .where(
            EvaluationResult.evaluation_run_id == run.id,
            EvaluationResult.organization_id == organization_id,
        )
        .order_by(EvaluationCase.position, EvaluationCase.created_at)
    ).all()
    run_ids = [result.actual_run_id for result, _ in rows if result.actual_run_id]
    traces = {}
    if run_ids:
        for trace in db.scalars(
            select(RunTrace).where(
                RunTrace.organization_id == organization_id,
                (RunTrace.agent_run_id.in_(run_ids)) | (RunTrace.team_run_id.in_(run_ids)),
            )
        ):
            traces[trace.agent_run_id or trace.team_run_id] = trace.id
    summary = run_summary(db, run, [result for result, _ in rows])
    return EvaluationRunDetail(
        **summary.model_dump(),
        target_snapshot=run.target_snapshot or {},
        results=[
            ResultResponse(
                id=result.id,
                case_id=case.id,
                case_name=case.name,
                case_position=case.position,
                target_kind=case.target_kind.value,
                input_text=case.input_text,
                expected=_expected(case),
                actual_run_type=result.actual_run_type,
                actual_run_id=result.actual_run_id,
                trace_id=traces.get(result.actual_run_id),
                status=result.status,
                passed=result.passed,
                score=result.score,
                checks=result.checks_json or [],
                failure_reasons=result.failure_reasons or [],
                actual=result.actual_json or {},
                duration_ms=result.duration_ms,
            )
            for result, case in rows
        ],
    )


def set_baseline(
    db: Session, organization_id: UUID, run_id: UUID, is_baseline: bool
) -> EvaluationRunSummary:
    run = get_run(db, organization_id, run_id)
    if is_baseline and run.status != EvaluationRunStatus.COMPLETED:
        raise APIError(409, "evaluation_not_completed", "Only completed runs can be a baseline.")
    if is_baseline:
        for other in db.scalars(
            select(EvaluationRun).where(
                EvaluationRun.dataset_id == run.dataset_id,
                EvaluationRun.organization_id == organization_id,
                EvaluationRun.is_baseline.is_(True),
            )
        ):
            other.is_baseline = False
    run.is_baseline = is_baseline
    db.commit()
    return run_summary(db, run)


def cancel_run(db: Session, organization_id: UUID, run_id: UUID) -> EvaluationRunSummary:
    """M7 cooperative cancellation: queued stops now; running stops before its next case."""
    run = db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == run_id, EvaluationRun.organization_id == organization_id)
        .with_for_update()
    )
    if run is None:
        raise APIError(404, "evaluation_run_not_found", "Evaluation run not found.")
    jobs = list(
        db.scalars(
            select(ExecutionJob)
            .where(
                ExecutionJob.evaluation_run_id == run.id,
                ExecutionJob.organization_id == organization_id,
                ExecutionJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .with_for_update()
        )
    )
    if not jobs:
        raise APIError(409, "nothing_to_cancel", "This evaluation is not running.")
    moment = datetime.now(UTC)
    for job in jobs:
        job.cancellation_requested_at = job.cancellation_requested_at or moment
        if job.status != JobStatus.RUNNING:
            job.status, job.completed_at = JobStatus.CANCELLED, moment
            job.error_code, job.error_message = "cancelled", "The evaluation was cancelled."
            run.status, run.completed_at = EvaluationRunStatus.CANCELLED, moment
    db.commit()
    return run_summary(db, run)


def compare(
    db: Session, organization_id: UUID, run_id: UUID, other_id: UUID
) -> EvaluationComparison:
    """`other_id` is the previous run (e.g. the baseline); `run_id` the current one."""
    current = get_run(db, organization_id, run_id)
    previous = get_run(db, organization_id, other_id)
    if current.dataset_id != previous.dataset_id:
        raise APIError(409, "different_datasets", "Only runs of the same dataset can be compared.")
    current_detail = run_detail(db, organization_id, current.id)
    previous_detail = run_detail(db, organization_id, previous.id)
    before = {result.case_id: result for result in previous_detail.results}
    after = {result.case_id: result for result in current_detail.results}
    changes = []
    for case_id in list(before) + [item for item in after if item not in before]:
        old, new = before.get(case_id), after.get(case_id)
        if old is None:
            change = "new"
        elif new is None:
            change = "removed"
        elif old.passed and not new.passed:
            change = "regression"
        elif not old.passed and new.passed:
            change = "improvement"
        else:
            change = "unchanged"
        source = new or old
        changes.append(
            CaseChange(
                case_id=case_id,
                case_name=source.case_name,
                previous_status=old.status.value if old else None,
                current_status=new.status.value if new else None,
                previous_score=old.score if old else None,
                current_score=new.score if new else None,
                change=change,
                failed_checks=[c["name"] for c in (new.checks if new else []) if not c["passed"]],
            )
        )
    order = {"regression": 0, "improvement": 1, "new": 2, "removed": 3, "unchanged": 4}
    position = {
        result.case_id: result.case_position for result in [*after.values(), *before.values()]
    }
    changes.sort(key=lambda item: (order[item.change], position.get(item.case_id, 0)))
    pair = (previous_detail.pass_rate, current_detail.pass_rate)
    scores = (previous_detail.score, current_detail.score)
    durations = (previous_detail.duration_ms, current_detail.duration_ms)
    return EvaluationComparison(
        previous=EvaluationRunSummary(**previous_detail.model_dump()),
        current=EvaluationRunSummary(**current_detail.model_dump()),
        pass_rate_change=round(pair[1] - pair[0], 4) if None not in pair else None,
        score_change=round(scores[1] - scores[0], 4) if None not in scores else None,
        duration_change_ms=durations[1] - durations[0] if None not in durations else None,
        config_changed=current.config_hash != previous.config_hash,
        regressions=sum(1 for item in changes if item.change == "regression"),
        improvements=sum(1 for item in changes if item.change == "improvement"),
        unchanged=sum(1 for item in changes if item.change == "unchanged"),
        cases=changes,
    )
