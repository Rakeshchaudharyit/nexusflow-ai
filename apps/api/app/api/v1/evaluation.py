from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    Database,
    JobQueueDep,
    require_organization_role,
)
from app.evaluation import service
from app.models.evaluation import EvaluationRunStatus
from app.models.identity import OrganizationMembership, Role
from app.schemas.evaluation import (
    CaseInput,
    CaseResponse,
    CaseUpdate,
    DatasetCreate,
    DatasetDetail,
    DatasetResponse,
    DatasetUpdate,
    DemoDatasetCreate,
    EvaluationComparison,
    EvaluationRunCreate,
    EvaluationRunDetail,
    EvaluationRunSummary,
    EvaluationRunUpdate,
)

router = APIRouter(tags=["evaluation"])
EvaluationManager = Annotated[
    OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
]


@router.get("/evaluation-datasets", response_model=list[DatasetResponse])
def list_datasets(membership: CurrentMembership, db: Database):
    return service.list_datasets(db, membership.organization_id)


@router.post("/evaluation-datasets", response_model=DatasetDetail, status_code=201)
def create_dataset(
    data: DatasetCreate, membership: EvaluationManager, user: CurrentUser, db: Database
):
    return service.create_dataset(db, membership.organization_id, user, data)


@router.post("/evaluation-datasets/demo", response_model=DatasetDetail, status_code=201)
def create_demo_dataset(
    data: DemoDatasetCreate, membership: EvaluationManager, user: CurrentUser, db: Database
):
    return service.create_demo_dataset(
        db, membership.organization_id, user, data.name, data.knowledge_agent_id
    )


@router.get("/evaluation-datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: UUID, membership: CurrentMembership, db: Database):
    return service.dataset_detail(db, membership.organization_id, dataset_id)


@router.patch("/evaluation-datasets/{dataset_id}", response_model=DatasetDetail)
def update_dataset(
    dataset_id: UUID, data: DatasetUpdate, membership: EvaluationManager, db: Database
):
    return service.update_dataset(db, membership.organization_id, dataset_id, data)


@router.delete("/evaluation-datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: UUID, membership: EvaluationManager, db: Database):
    service.delete_dataset(db, membership.organization_id, dataset_id)


@router.post(
    "/evaluation-datasets/{dataset_id}/cases", response_model=CaseResponse, status_code=201
)
def add_case(dataset_id: UUID, data: CaseInput, membership: EvaluationManager, db: Database):
    return service.add_case(db, membership.organization_id, dataset_id, data)


@router.patch("/evaluation-cases/{case_id}", response_model=CaseResponse)
def update_case(case_id: UUID, data: CaseUpdate, membership: EvaluationManager, db: Database):
    return service.update_case(db, membership.organization_id, case_id, data)


@router.delete("/evaluation-cases/{case_id}", status_code=204)
def delete_case(case_id: UUID, membership: EvaluationManager, db: Database):
    service.delete_case(db, membership.organization_id, case_id)


@router.post(
    "/evaluation-datasets/{dataset_id}/runs",
    response_model=EvaluationRunSummary,
    status_code=201,
)
def start_run(
    dataset_id: UUID,
    data: EvaluationRunCreate,
    membership: EvaluationManager,
    user: CurrentUser,
    db: Database,
    queue: JobQueueDep,
    request: Request,
):
    return service.start_run(
        db,
        request.app.state.settings,
        queue,
        membership.organization_id,
        user,
        dataset_id,
        data.target_agent_id,
        data.target_team_id,
    )


@router.get("/evaluation-runs", response_model=list[EvaluationRunSummary])
def list_runs(
    membership: CurrentMembership,
    db: Database,
    dataset_id: UUID | None = None,
    status: EvaluationRunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_runs(db, membership.organization_id, dataset_id, status, limit)


@router.get("/evaluation-runs/{run_id}", response_model=EvaluationRunDetail)
def get_run(run_id: UUID, membership: CurrentMembership, db: Database, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.run_detail(db, membership.organization_id, run_id)


@router.patch("/evaluation-runs/{run_id}", response_model=EvaluationRunSummary)
def update_run(
    run_id: UUID, data: EvaluationRunUpdate, membership: EvaluationManager, db: Database
):
    return service.set_baseline(db, membership.organization_id, run_id, data.is_baseline)


@router.post("/evaluation-runs/{run_id}/cancel", response_model=EvaluationRunSummary)
def cancel_run(run_id: UUID, membership: EvaluationManager, db: Database):
    return service.cancel_run(db, membership.organization_id, run_id)


@router.get("/evaluation-runs/{run_id}/compare/{other_id}", response_model=EvaluationComparison)
def compare_runs(run_id: UUID, other_id: UUID, membership: CurrentMembership, db: Database):
    return service.compare(db, membership.organization_id, run_id, other_id)
