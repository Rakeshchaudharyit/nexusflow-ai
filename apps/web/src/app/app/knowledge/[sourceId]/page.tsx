import { SourceDetail } from "@/components/knowledge/source-detail";

export const metadata = { title: "Knowledge source · NexusFlow AI" };

export default async function KnowledgeSourcePage({
  params,
}: {
  params: Promise<{ sourceId: string }>;
}) {
  const { sourceId } = await params;
  return <SourceDetail key={sourceId} sourceId={sourceId} />;
}
