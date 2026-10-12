"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { APIError } from "@/lib/api/auth";
import { POLL_INTERVAL_MS } from "@/lib/jobs";

export function describeError(failure: unknown): string {
  return failure instanceof Error
    ? failure.message
    : "Request failed. Please try again.";
}

type Loaded<T> = {
  source: () => Promise<T>;
  data: T | null;
  error: string | null;
  status: number | null;
};

/** Loads `load` and reloads whenever its identity changes (wrap it in useCallback). */
export function useResource<T>(load: () => Promise<T>) {
  const { reload: restoreSession } = useAuth();
  const [result, setResult] = useState<Loaded<T> | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    load().then(
      (data) => {
        if (live) setResult({ source: load, data, error: null, status: null });
      },
      (failure: unknown) => {
        if (!live) return;
        if (failure instanceof APIError && failure.status === 401)
          void restoreSession();
        const status = failure instanceof APIError ? failure.status : null;
        setResult((previous) =>
          // A failed refresh (for example after an action, while the API is down) keeps
          // what is already on screen; only a 404 means the resource is gone.
          previous?.source === load && previous.data !== null && status !== 404
            ? { ...previous, error: describeError(failure) }
            : { source: load, data: null, error: describeError(failure), status },
        );
      },
    );
    return () => {
      live = false;
    };
  }, [load, version, restoreSession]);
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const current = result?.source === load ? result : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    notFound: current?.status === 404,
    loading: current === null,
    reload,
  };
}

/** Calls `refresh` every POLL_INTERVAL_MS while `active` (bounded polling, M7). Stops when
 * the run settles, and on unmount, which includes every workspace switch (the shell remounts
 * workspace pages), so a previous organization's run is never polled into view. */
export function usePolling(active: boolean, refresh: () => void) {
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, refresh]);
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

export function formatDuration(value: number | null): string {
  if (value === null) return "—";
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;
}

export function preview(text: string, length = 80): string {
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}
