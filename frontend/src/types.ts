export type Health = {
  status: string;
  uptime_s: number;
  provider: string;
  model_main: string;
  model_sub: string;
  fallback_configured: boolean;
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
  unverified: boolean;
  tokens_may_be_underreported: boolean;
  thinking_replay_broken: boolean;
  agents: AgentNode[];
  slots: ArtifactSlot[];
  final_answer: string;
};

export type ArtifactSlot = {
  key: string;
  owner: string;
  status: "filled" | "missing";
  version: number;
  chars: number;
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