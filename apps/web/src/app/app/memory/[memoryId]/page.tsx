import { MemoryDetail } from "@/components/memory/memory-detail";

export const metadata = { title: "Memory · NexusFlow AI" };

export default async function MemoryEntryPage({ params }: { params: Promise<{ memoryId: string }> }) {
  const { memoryId } = await params;
  return <MemoryDetail key={memoryId} memoryId={memoryId} />;
}
