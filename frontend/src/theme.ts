export const colors = {
  bg: "#0f1115",
  panel: "#161a21",
  panelAlt: "#1b2029",
  border: "#2a2f37",
  text: "#e6e9ee",
  muted: "#8b95a3",
  green: "#6ee7a8",
  red: "#f87171",
  amber: "#fbbf24",
  blue: "#60a5fa",
  purple: "#c084fc",
  cyan: "#22d3ee",
};

export const panelStyle = {
  border: `1px solid ${colors.border}`,
  borderRadius: 8,
  background: colors.panel,
  padding: 12,
  marginBottom: 12,
} as const;

export const mutedStyle = { color: colors.muted } as const;

export function statusColor(status: string): string {
  switch (status) {
    case "done":
      return colors.green;
    case "running":
      return colors.blue;
    case "queued":
      return colors.cyan;
    case "partial":
      return colors.amber;
    case "budget_exhausted":
    case "interrupted":
      return colors.amber;
    case "failed":
    case "config_error":
      return colors.red;
    case "cancelled":
      return colors.muted;
    default:
      return colors.text;
  }
}

export function eventColor(kind: string): string {
  if (kind === "run_finished" || kind === "review_passed" || kind === "agent_finished") {
    return colors.green;
  }
  if (kind === "agent_failed" || kind === "budget_exhausted" || kind === "review_rejected") {
    return colors.red;
  }
  if (kind.startsWith("budget") || kind === "limit_reached" || kind === "run_interrupted") {
    return colors.amber;
  }
  if (kind.startsWith("artifact")) {
    return colors.purple;
  }
  if (kind.startsWith("tool") || kind === "invalid_tool_call") {
    return colors.cyan;
  }
  if (kind === "provider_fallback" || kind === "breaker_open" || kind === "stall_warning") {
    return colors.red;
  }
  return colors.muted;
}

export function timeOf(ts: number): string {
  const date = new Date(ts * 1000);
  return date.toLocaleTimeString(undefined, { hour12: false });
}

export function clip(text: string, limit: number): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}…`;
}

export function yuan(value: number): string {
  return `¥${value.toFixed(4)}`;
}