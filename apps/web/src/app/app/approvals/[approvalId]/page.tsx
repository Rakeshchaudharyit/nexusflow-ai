import { ApprovalDetail } from "@/components/approvals/approval-detail";

export const metadata = { title: "Approval · NexusFlow AI" };

export default async function ApprovalPage({
  params,
}: {
  params: Promise<{ approvalId: string }>;
}) {
  const { approvalId } = await params;
  return <ApprovalDetail key={approvalId} approvalId={approvalId} />;
}
