import type { FailureMode, Health, RunListItem, RunSummary } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = `${init?.method ?? "GET"} ${path} -> ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail && typeof body.detail === "object") {
        const obj = body.detail as { detail?: string; error?: string };
        detail = [obj.error, obj.detail].filter(Boolean).join(": ") || detail;
      }
    } catch {
      // keep the status line
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function postJson<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchHealth(): Promise<Health> {
  return request<Health>("/health");
}

export function listRuns(): Promise<{ runs: RunListItem[] }> {
  return request<{ runs: RunListItem[] }>("/api/runs");
}

export function createRun(body: {
  task: string;
  budget_tokens?: number;
  max_depth?: number;
  max_concurrency?: number;
}): Promise<{ run_id: string; status: string }> {
  return postJson("/api/runs", body);
}

export function fetchRun(runId: string): Promise<RunSummary> {
  return request<RunSummary>(`/api/runs/${runId}`);
}

export function cancelRun(runId: string): Promise<{ run_id: string; status: string }> {
  return postJson(`/api/runs/${runId}/cancel`);
}

export function resumeRun(
  runId: string,
  extraBudgetTokens?: number,
): Promise<{ run_id: string; status: string; budget_tokens: number }> {
  return postJson(
    `/api/runs/${runId}/resume`,
    extraBudgetTokens ? { extra_budget_tokens: extraBudgetTokens } : {},
  );
}

export function patchDebug(
  runId: string,
  body: {
    budget_tokens?: number;
    max_depth?: number;
    max_concurrency?: number;
    fail_next?: boolean;
  },
): Promise<{ ok: boolean; fail_next: boolean }> {
  return request(`/api/runs/${runId}/debug`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getFailureMode(): Promise<{ mode: FailureMode; remaining: number | null }> {
  return request("/api/debug/failures");
}

export function setFailureMode(
  mode: FailureMode,
  calls?: number | null,
): Promise<{ mode: FailureMode; remaining: number | null }> {
  return postJson("/api/debug/failures", { mode, calls: calls ?? null });
}

export function runStreamUrl(runId: string, lastEventId: number): string {
  const suffix = lastEventId > 0 ? `?last_event_id=${lastEventId}` : "";
  return `/api/runs/${runId}/stream${suffix}`;
}