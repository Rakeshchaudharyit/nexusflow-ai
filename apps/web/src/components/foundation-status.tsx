"use client";

import { useEffect, useState } from "react";
import { fetchReadiness, type Readiness } from "@/lib/api/client";

type State =
  | { phase: "loading" }
  | { phase: "success"; data: Readiness }
  | { phase: "error" };

export function FoundationStatus({ compact = false }: { compact?: boolean }) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetchReadiness(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ phase: "success", data });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ phase: "error" });
      });
    return () => controller.abort();
  }, [attempt]);
  const statuses = [
    {
      name: "Frontend",
      detail: "Next.js / React",
      status: "Connected",
      ok: true,
    },
    ...(["api", "postgres", "redis"] as const).map((key) => ({
      name: { api: "API", postgres: "PostgreSQL", redis: "Redis" }[key],
      detail: {
        api: "FastAPI / v1",
        postgres: "Relational storage",
        redis: "Infrastructure cache",
      }[key],
      status:
        state.phase === "loading"
          ? "Checking…"
          : state.phase === "error"
            ? key === "api"
              ? "Unavailable"
              : "Unknown"
            : state.data.services[key] === "ok"
              ? "Connected"
              : "Unavailable",
      ok: state.phase === "success" && state.data.services[key] === "ok",
    })),
  ];
  return (
    <section className={`status-panel${compact ? " compact-status" : ""}`} aria-labelledby="status-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">SYSTEM CHECK</p>
          <h2 id="status-title">Platform readiness</h2>
        </div>
        <button
          disabled={state.phase === "loading"}
          onClick={() => {
            setState({ phase: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          ↻ <span>Refresh</span>
        </button>
      </div>
      <div
        className="status-list"
        aria-live="polite"
        aria-busy={state.phase === "loading"}
      >
        {statuses.filter(service => !compact || service.name !== "Frontend").map((service) => (
          <div className="status-row" key={service.name}>
            <div>
              <h3>{service.name}</h3>
              <p>{service.detail}</p>
            </div>
            <span className={`badge ${service.ok ? "connected" : "pending"}`}>
              <i aria-hidden="true" />
              {service.status}
            </span>
          </div>
        ))}
      </div>
      <p className="status-note">
        {state.phase === "loading"
          ? "Checking API and infrastructure connectivity…"
          : state.phase === "error"
            ? "The API could not be reached. Check that the stack is running, then refresh."
            : state.data.status === "ready"
              ? "All foundation services are ready. Status verified by the API."
              : "The API is reachable. One or more dependencies need attention."}
      </p>
    </section>
  );
}
