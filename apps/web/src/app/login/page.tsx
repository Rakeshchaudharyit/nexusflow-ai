import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth-form";
import { signedIn } from "@/lib/api/server";
import { returnPath } from "@/lib/return-path";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sign in · NexusFlow AI" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  if (await signedIn()) {
    const { next } = await searchParams;
    redirect(returnPath(typeof next === "string" ? next : null));
  }
  return <AuthForm mode="login" />;
}
