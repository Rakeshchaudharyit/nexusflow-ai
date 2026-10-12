import { TeamDetail } from "@/components/teams/team-detail";

export const metadata = { title: "Team · NexusFlow AI" };

export default async function TeamPage({ params }: { params: Promise<{ teamId: string }> }) {
  const { teamId } = await params;
  return <TeamDetail key={teamId} teamId={teamId} />;
}
