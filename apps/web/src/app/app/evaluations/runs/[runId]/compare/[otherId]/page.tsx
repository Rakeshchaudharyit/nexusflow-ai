import { EvaluationCompare } from "@/components/evaluation/compare";

export const metadata = { title: "Compare evaluations · NexusFlow AI" };

export default async function ComparePage({
  params,
}: {
  params: Promise<{ runId: string; otherId: string }>;
}) {
  const { runId, otherId } = await params;
  return <EvaluationCompare key={`${runId}:${otherId}`} runId={runId} otherId={otherId} />;
}
