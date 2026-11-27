export type Health = {
  status: string;
  uptime_s: number;
  provider: string;
  model_main: string;
  model_sub: string;
  fallback_configured: boolean;
  failure_inject_mode: string;
};

export type AgentStatus =
  | "queued"
  | "running"
  | "done"
  | "partial"
  | "failed"
  | "cancelled"
  | "config_error";

export type AgentNode = {
  id: string;
  role: string;
  parent_id: string | null;
  depth: number;
  status: AgentStatus;
  task: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  latency_ms: number;
  steps: number;
  summary: string;
  error_kind: string;
  artifact_keys: string[];
};

export type RunStatus =
  | "queued"
  | "running"
  | "done"
  | "budget_exhausted"
  | "cancelled"
  | "failed"
  | "interrupted";

export type RunSummary = {
  run_id: string;
  task: string;
  status: RunStatus;
  budget_tokens: number;
  tokens_used: number;
  reserved_tokens: number;
  cost: number;
  elapsed_s: number;
  max_depth: number;
  max_concurrency: number;
  unverified: boolean;
  tokens_may_be_underreported: boolean;
  thinking_replay_broken: boolean;
  agents: AgentNode[];
  slots: ArtifactSlot[];
  final_answer: string;
  budget_hard_stop: boolean;
  debug: Record<string, unknown>;
};

export type RunListItem = {
  run_id: string;
  task: string;
  status: RunStatus;
  tokens_used: number;
  cost: number;
  agents: number;
  created_at: number;
};

export type ArtifactSlot = {
  key: string;
  owner: string;
  status: "filled" | "missing";
  version: number;
  chars: number;
  last_agent?: string;
};

export type ConversationToolCall = {
  id: string;
  type?: string;
  function: { name: string; arguments: string };
};

export type ConversationMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content?: string | null;
  reasoning_content?: string | null;
  tool_calls?: ConversationToolCall[];
  tool_call_id?: string;
};

export type AgentConversation = {
  agent_id: string;
  role: string;
  status: AgentStatus;
  task: string;
  messages: ConversationMessage[];
};

export type RunEvent = {
  id: number;
  ts: number;
  kind: string;
  agent_id?: string;
  role?: string;
  depth?: number;
  parent?: string | null;
  summary?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
  latency_ms?: number;
  data?: Record<string, unknown>;
};

export type TickEvent = {
  seq: number;
  ts: number;
  uptime_s: number;
  replayed?: boolean;
};

export type FailureMode = "off" | "transient" | "permanent" | "structural" | "task";

export const TERMINAL_RUN_STATUSES: RunStatus[] = [
  "done",
  "failed",
  "cancelled",
  "interrupted",
  "budget_exhausted",
];

export function isTerminal(status: RunStatus | undefined): boolean {
  return status !== undefined && TERMINAL_RUN_STATUSES.includes(status);
}

export function missingSlots(slots: ArtifactSlot[]): string[] {
  const missing: string[] = [];
  if (!slots.some((slot) => slot.key.startsWith("writer."))) {
    missing.push("writer.*");
  }
  if (!slots.some((slot) => slot.key.startsWith("marketing."))) {
    missing.push("marketing.*");
  }
  if (!slots.some((slot) => slot.key === "reviewer.verdict")) {
    missing.push("reviewer.verdict");
  }
  return missing;
}