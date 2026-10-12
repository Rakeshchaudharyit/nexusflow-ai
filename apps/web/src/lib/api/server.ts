import { cookies } from "next/headers";
import type { User } from "./auth";

export function backendURL(path: string): string {
  const base = process.env.API_INTERNAL_URL;
  if (!base) throw new Error("API_INTERNAL_URL is required.");
  const url = new URL(base);
  if (!["http:", "https:"].includes(url.protocol))
    throw new Error("API_INTERNAL_URL must use HTTP or HTTPS.");
  return `${base.replace(/\/$/, "")}${path}`;
}

export function cookieName(): string {
  return process.env.AUTH_COOKIE_NAME || "nexusflow_refresh";
}

export async function getServerUser(): Promise<User | null> {
  const cookie = (await cookies()).get(cookieName());
  if (!cookie) return null;
  const response = await fetch(backendURL("/auth/session"), {
    headers: { Cookie: `${cookie.name}=${cookie.value}` },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Session verification unavailable.");
  return response.json() as Promise<User>;
}

/** Sign-in pages send an already signed-in visitor on to the workspace. */
export async function signedIn(): Promise<boolean> {
  try {
    return (await getServerUser()) !== null;
  } catch {
    // The API is unreachable: show the form, which reports the outage on submit.
    return false;
  }
}
