import { EvaluationRunDetail } from "@/components/evaluation/run-detail";

export const metadata = { title: "Evaluation run · NexusFlow AI" };

export default async function EvaluationRunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <EvaluationRunDetail key={runId} runId={runId} />;
}
