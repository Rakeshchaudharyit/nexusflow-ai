import { TraceDetail } from "@/components/observability/trace-detail";

export const metadata = { title: "Trace · NexusFlow AI" };

export default async function TracePage({ params }: { params: Promise<{ traceId: string }> }) {
  const { traceId } = await params;
  return <TraceDetail key={traceId} traceId={traceId} />;
}
