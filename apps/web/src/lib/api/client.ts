export type DependencyStatus = "ok" | "unavailable";
export type Readiness = {
  status: "ready" | "not_ready";
  services: { api: "ok"; postgres: DependencyStatus; redis: DependencyStatus };
};

function isReadiness(value: unknown): value is Readiness {
  if (
    typeof value !== "object" ||
    value === null ||
    !("status" in value) ||
    !("services" in value)
  )
    return false;
  const services = value.services;
  if (typeof services !== "object" || services === null) return false;
  return (
    (value.status === "ready" || value.status === "not_ready") &&
    "api" in services &&
    services.api === "ok" &&
    "postgres" in services &&
    (services.postgres === "ok" || services.postgres === "unavailable") &&
    "redis" in services &&
    (services.redis === "ok" || services.redis === "unavailable")
  );
}

export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!baseUrl) throw new Error("NEXT_PUBLIC_API_URL is not configured.");
  const url = new URL(baseUrl);
  if (!["http:", "https:"].includes(url.protocol))
    throw new Error("API URL must use HTTP or HTTPS.");
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/health/ready`, {
    cache: "no-store",
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(7000)])
      : AbortSignal.timeout(7000),
  });
  if (response.status !== 200 && response.status !== 503)
    throw new Error("API unavailable.");
  const data: unknown = await response.json();
  if (!isReadiness(data)) throw new Error("Unexpected readiness response.");
  return data;
}
