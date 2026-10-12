"use client";

export type Role = "owner" | "admin" | "member";
export type Organization = {
  id: string;
  name: string;
  slug: string;
  role: Role;
};
export type User = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  is_verified: boolean;
  organizations: Organization[];
};
export type AuthResult = {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
};
export type Registration = {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  organization_name: string;
};
export class APIError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let expiresAt = 0;
let refreshFlight: Promise<User> | null = null;

async function sessionLock<T>(operation: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks)
    return navigator.locks.request("nexusflow-session", operation);
  return operation();
}

async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/backend${path}`, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    throw new APIError(
      0,
      "unavailable",
      "The API could not be reached. Please try again.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new APIError(
      response.status,
      data?.error?.code ?? "request_error",
      data?.error?.message ?? "The request could not be completed.",
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function acceptSession(result: AuthResult): User {
  accessToken = result.access_token;
  expiresAt = Date.now() + result.expires_in * 1000;
  return result.user;
}

export function clearAccessToken() {
  accessToken = null;
  expiresAt = 0;
}

export function refreshSession(): Promise<User> {
  if (!refreshFlight) {
    refreshFlight = sessionLock(async () => {
      try {
        return acceptSession(
          await send<AuthResult>("/auth/refresh", { method: "POST" }),
        );
      } catch (error) {
        clearAccessToken();
        throw error;
      }
    }).finally(() => {
      refreshFlight = null;
    });
  }
  return refreshFlight;
}

export async function authenticated<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  if (!accessToken || Date.now() >= expiresAt) await refreshSession();
  const usedToken = accessToken;
  const attempt = () =>
    send<T>(path, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${accessToken}` },
    });
  try {
    return await attempt();
  } catch (error) {
    if (!(error instanceof APIError) || error.status !== 401) throw error;
    if (accessToken === usedToken) await refreshSession();
    try {
      return await attempt();
    } catch (retryError) {
      if (retryError instanceof APIError && retryError.status === 401)
        clearAccessToken();
      throw retryError;
    }
  }
}

// Tenant requests name their organization explicitly; the API re-validates membership.
export const scoped = (organizationId: string, init: RequestInit = {}) => ({
  ...init,
  headers: {
    ...init.headers,
    "X-Organization-ID": organizationId,
    ...(init.body ? { "Content-Type": "application/json" } : {}),
  },
});

export async function login(email: string, password: string): Promise<User> {
  return sessionLock(async () =>
    acceptSession(
      await send<AuthResult>("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      }),
    ),
  );
}
export async function register(input: Registration): Promise<User> {
  return sessionLock(async () =>
    acceptSession(
      await send<AuthResult>("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      }),
    ),
  );
}
export async function logout(): Promise<void> {
  await sessionLock(() => send<void>("/auth/logout", { method: "POST" }));
  clearAccessToken();
}
export const getCurrentUser = () => authenticated<User>("/auth/me");
export const listOrganizations = () =>
  authenticated<Organization[]>("/organizations");
export const getOrganization = (id: string) =>
  authenticated<Organization>(`/organizations/${encodeURIComponent(id)}`);
export const getCurrentOrganization = (id: string) =>
  authenticated<Organization>("/organizations/current", {
    headers: { "X-Organization-ID": id },
  });
export const createOrganization = (name: string) =>
  authenticated<Organization>("/organizations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
