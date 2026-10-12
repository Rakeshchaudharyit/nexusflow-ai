import type { TeamRole } from "@/lib/api/teams";

export const ROLE_LABELS: Record<TeamRole, string> = {
  supervisor: "Supervisor",
  customer_specialist: "Customer Specialist",
  researcher: "Researcher",
  analyst: "Analyst",
  writer: "Writer",
  validator: "Validator",
};
export const ROLES = Object.keys(ROLE_LABELS) as TeamRole[];
export const roleLabel = (role: string | null) =>
  role ? (ROLE_LABELS[role as TeamRole] ?? role) : "Team";
