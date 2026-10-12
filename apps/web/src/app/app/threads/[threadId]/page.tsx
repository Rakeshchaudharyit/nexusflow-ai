import { ThreadDetail } from "@/components/memory/thread-detail";

export const metadata = { title: "Thread · NexusFlow AI" };

export default async function ThreadPage({ params }: { params: Promise<{ threadId: string }> }) {
  const { threadId } = await params;
  return <ThreadDetail key={threadId} threadId={threadId} />;
}
