"use client";

import { authenticated, scoped } from "./auth";

export type EvaluationRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ResultStatus = "passed" | "failed" | "error";

export type EvaluationCase = {
  id: string;
  dataset_id: string;
  position: number;
  name: string;
  target_kind: "agent" | "team";
  target_agent_id: string | null;
  target_team_id: string | null;
  input_text: string;
  setup_inputs: string[];
  setup_memory: string[];
  expected_status: string | null;
  expected_intent: string | null;
  expected_tool_key: string | null;
  expected_output_contains: string[];
  expected_output_excludes: string[];
  expected_values: Record<string, unknown>;
  expected_citation_documents: string[];
  expected_no_match: boolean;
  expected_policy_decision: string | null;
  expected_action_type: string | null;
  retrieval_k: number;
};
export type CaseInput = Partial<Omit<EvaluationCase, "id" | "dataset_id">> & {
  name: string;
  input_text: string;
};
export type EvaluationRunSummary = {
  id: string;
  dataset_id: string;
  dataset_name: string | null;
  status: EvaluationRunStatus;
  target_type: string;
  target_agent_id: string | null;
  target_team_id: string | null;
  target_names: string[];
  config_hash: string | null;
  is_baseline: boolean;
  case_count: number;
  passed_count: number;
  failed_count: number;
  error_count: number;
  pass_rate: number | null;
  score: number | null;
  duration_ms: number | null;
  retrieval_hit_rate: number | null;
  retrieval_mrr: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};
export type Check = { name: string; passed: boolean; expected: unknown; actual: unknown };
export type RetrievedItem = {
  rank: number;
  citation_id: string | null;
  document_name: string | null;
  page: number | null;
  score: number | null;
};
export type EvaluationResult = {
  id: string;
  case_id: string;
  case_name: string;
  case_position: number;
  target_kind: "agent" | "team";
  input_text: string;
  expected: Record<string, unknown>;
  actual_run_type: "agent" | "team" | null;
  actual_run_id: string | null;
  trace_id: string | null;
  status: ResultStatus;
  passed: boolean;
  score: number;
  checks: Check[];
  failure_reasons: string[];
  actual: {
    status?: string;
    intent?: string | null;
    tools?: string[];
    text?: string;
    policy_decision?: string | null;
    action_type?: string | null;
    cited_documents?: string[];
    retrieved?: RetrievedItem[];
    retrieval?: { hit_at_k: boolean; k: number; rank: number | null; reciprocal_rank: number };
  };
  duration_ms: number | null;
};
export type EvaluationRunDetail = EvaluationRunSummary & {
  target_snapshot: Record<string, unknown>;
  results: EvaluationResult[];
};
export type EvaluationDataset = {
  id: string;
  name: string;
  description: string;
  dataset_type: string;
  status: "active" | "archived";
  created_at: string;
  updated_at: string;
  case_count: number;
  run_count: number;
  last_run: EvaluationRunSummary | null;
};
export type DatasetDetail = EvaluationDataset & {
  cases: EvaluationCase[];
  runs: EvaluationRunSummary[];
};
export type CaseChange = {
  case_id: string;
  case_name: string;
  previous_status: string | null;
  current_status: string | null;
  previous_score: number | null;
  current_score: number | null;
  change: "regression" | "improvement" | "unchanged" | "new" | "removed";
  failed_checks: string[];
};
export type EvaluationComparison = {
  previous: EvaluationRunSummary;
  current: EvaluationRunSummary;
  pass_rate_change: number | null;
  score_change: number | null;
  duration_change_ms: number | null;
  config_changed: boolean;
  regressions: number;
  improvements: number;
  unchanged: number;
  cases: CaseChange[];
};

const id = (value: string) => encodeURIComponent(value);
const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const listDatasets = (organizationId: string) =>
  authenticated<EvaluationDataset[]>("/evaluation-datasets", scoped(organizationId));
export const createDataset = (
  organizationId: string,
  input: { name: string; description: string; dataset_type: string },
) =>
  authenticated<DatasetDetail>(
    "/evaluation-datasets",
    scoped(organizationId, json("POST", input)),
  );
export const createDemoDataset = (organizationId: string, knowledgeAgentId?: string) =>
  authenticated<DatasetDetail>(
    "/evaluation-datasets/demo",
    scoped(
      organizationId,
      json("POST", knowledgeAgentId ? { knowledge_agent_id: knowledgeAgentId } : {}),
    ),
  );
export const getDataset = (organizationId: string, datasetId: string) =>
  authenticated<DatasetDetail>(`/evaluation-datasets/${id(datasetId)}`, scoped(organizationId));
export const deleteDataset = (organizationId: string, datasetId: string) =>
  authenticated<void>(
    `/evaluation-datasets/${id(datasetId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
export const addCase = (organizationId: string, datasetId: string, input: CaseInput) =>
  authenticated<EvaluationCase>(
    `/evaluation-datasets/${id(datasetId)}/cases`,
    scoped(organizationId, json("POST", input)),
  );
export const deleteCase = (organizationId: string, caseId: string) =>
  authenticated<void>(
    `/evaluation-cases/${id(caseId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
export const startEvaluation = (
  organizationId: string,
  datasetId: string,
  targets: { target_agent_id?: string; target_team_id?: string },
) =>
  authenticated<EvaluationRunSummary>(
    `/evaluation-datasets/${id(datasetId)}/runs`,
    scoped(organizationId, json("POST", targets)),
  );
export const listEvaluationRuns = (organizationId: string, datasetId?: string) =>
  authenticated<EvaluationRunSummary[]>(
    `/evaluation-runs${datasetId ? `?dataset_id=${id(datasetId)}` : ""}`,
    scoped(organizationId),
  );
export const getEvaluationRun = (organizationId: string, runId: string) =>
  authenticated<EvaluationRunDetail>(`/evaluation-runs/${id(runId)}`, scoped(organizationId));
export const setBaseline = (organizationId: string, runId: string, isBaseline: boolean) =>
  authenticated<EvaluationRunSummary>(
    `/evaluation-runs/${id(runId)}`,
    scoped(organizationId, json("PATCH", { is_baseline: isBaseline })),
  );
export const cancelEvaluation = (organizationId: string, runId: string) =>
  authenticated<EvaluationRunSummary>(
    `/evaluation-runs/${id(runId)}/cancel`,
    scoped(organizationId, { method: "POST" }),
  );
export const compareRuns = (organizationId: string, runId: string, previousId: string) =>
  authenticated<EvaluationComparison>(
    `/evaluation-runs/${id(runId)}/compare/${id(previousId)}`,
    scoped(organizationId),
  );
