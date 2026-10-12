import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth-form";
import { signedIn } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata = { title: "Create workspace · NexusFlow AI" };

export default async function RegisterPage() {
  if (await signedIn()) redirect("/app");
  return <AuthForm mode="register" />;
}
