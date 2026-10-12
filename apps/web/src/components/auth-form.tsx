"use client";

import { NexusFlowLogo, NexusFlowMark } from "./ui/nexusflow-brand";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { returnPath } from "@/lib/return-path";
import { useAuth } from "./auth-provider";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const registering = mode === "register";
  const auth = useAuth();
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "");
    try {
      if (registering)
        await auth.signUp({
          first_name: value("first_name").trim(),
          last_name: value("last_name").trim(),
          email: value("email").trim(),
          password: value("password"),
          organization_name: value("organization_name").trim(),
        });
      else await auth.signIn(value("email").trim(), value("password"));
      router.replace(
        returnPath(new URLSearchParams(window.location.search).get("next")),
      );
      router.refresh();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <main className="auth-page identity-page">
      <div className="identity-editorial"><NexusFlowMark/><p className="eyebrow">NEXUSFLOW / CONTROL INFRASTRUCTURE</p><h2>Operate AI systems<br/>with control.</h2><p>Agents. Tools. Orchestration.<br/>One accountable workspace.</p><div className="identity-rail" aria-hidden="true"><span>01 / CONFIGURE</span><span>02 / ORCHESTRATE</span><span>03 / REVIEW</span></div></div>
      <Link href="/" className="brand">
        <NexusFlowLogo/>
      </Link>
      <section className="auth-card" aria-labelledby="auth-title">
        <p className="eyebrow">IDENTITY &amp; WORKSPACES</p>
        <h1 id="auth-title">
          {registering ? "Your workspace starts here." : "Welcome back."}
        </h1>
        <p className="auth-description">
          {registering
            ? "Create an account and a workspace for your team."
            : "Sign in to your NexusFlow workspace."}
        </p>
        <form onSubmit={submit} aria-busy={pending}>
          {registering && (
            <div className="form-grid">
              <label>
                First name
                <input
                  name="first_name"
                  autoComplete="given-name"
                  required
                  maxLength={80}
                  pattern=".*\S.*"
                />
              </label>
              <label>
                Last name
                <input
                  name="last_name"
                  autoComplete="family-name"
                  required
                  maxLength={80}
                  pattern=".*\S.*"
                />
              </label>
            </div>
          )}
          <label>
            {registering ? "Work email" : "Email"}
            <input
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={320}
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete={registering ? "new-password" : "current-password"}
              required
              minLength={registering ? 12 : 1}
              maxLength={128}
            />
          </label>
          {registering && (
            <>
              <p className="field-hint">
                Use at least 12 characters. Passwords are never stored in
                plaintext.
              </p>
              <label>
                Organization / Workspace name
                <input
                  name="organization_name"
                  autoComplete="organization"
                  required
                  maxLength={120}
                  pattern=".*\S.*"
                />
              </label>
            </>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="primary-button" type="submit" disabled={pending}>
            {pending
              ? registering
                ? "Creating workspace…"
                : "Signing in…"
              : registering
                ? "Create workspace"
                : "Sign in"}
          </button>
        </form>
        <p className="auth-alternative">
          {registering ? "Already have an account?" : "New to NexusFlow?"}{" "}
          <Link href={registering ? "/login" : "/register"}>
            {registering ? "Sign in" : "Create account"}
          </Link>
        </p>
      </section>
      <p className="auth-footer">Secure identity · Isolated workspaces</p>
    </main>
  );
}
