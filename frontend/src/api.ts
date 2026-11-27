import type { Health, RunEvent, RunSummary } from "./types";

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}`);
  }
  return (await res.json()) as T;
}

export function fetchHealth(): Promise<Health> {
  return getJson<Health>("/health");
}

export function createRun(body: {
  task: string;
  budget_tokens?: number;
  max_depth?: number;
  max_concurrency?: number;
}): Promise<{ run_id: string }> {
  return getJson("/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchRun(runId: string): Promise<RunSummary> {
  return getJson<RunSummary>(`/api/runs/${runId}`);
}

export function patchDebug(
  runId: string,
  body: Record<string, unknown>,
): Promise<{ ok: boolean }> {
  return getJson(`/api/runs/${runId}/debug`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function cancelRun(runId: string): Promise<{ ok: boolean }> {
  return getJson(`/api/runs/${runId}/cancel`, { method: "POST" });
}

export function resumeRun(runId: string): Promise<{ ok: boolean }> {
  return getJson(`/api/runs/${runId}/resume`, { method: "POST" });
}

export function openRunEvents(
  runId: string,
  handlers: {
    onEvent: (event: RunEvent) => void;
    onError?: () => void;
  },
): EventSource {
  const source = new EventSource(`/api/runs/${runId}/events`);
  source.onmessage = (message) => {
    try {
      handlers.onEvent(JSON.parse(message.data) as RunEvent);
    } catch {
      // ignore malformed frames
    }
  };
  source.onerror = () => handlers.onError?.();
  return source;
}