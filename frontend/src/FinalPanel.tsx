import { colors, statusColor, yuan } from "./theme";
import { isTerminal, missingSlots, type RunSummary } from "./types";

export function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        border: `1px solid ${color}`,
        color,
        borderRadius: 999,
        padding: "1px 8px",
        fontSize: 11,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

export function FinalPanel({ run }: { run: RunSummary }) {
  const verdict = run.debug["review_verdict"];
  const missing = isTerminal(run.status) ? missingSlots(run.slots) : [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <Pill label={`run ${run.status}`} color={statusColor(run.status)} />
        {run.unverified ? (
          <Pill label="unverified" color={colors.amber} />
        ) : (
          <Pill label="verified" color={colors.green} />
        )}
        {typeof verdict === "string" && verdict ? (
          <Pill label={`review ${verdict}`} color={verdict === "PASS" ? colors.green : colors.red} />
        ) : null}
        {run.tokens_may_be_underreported ? <Pill label="tokens may be under-reported" color={colors.amber} /> : null}
        {run.thinking_replay_broken ? <Pill label="thinking replay issue" color={colors.red} /> : null}
        <Pill label={`${run.tokens_used.toLocaleString()} tokens`} color={colors.muted} />
        <Pill label={yuan(run.cost)} color={colors.muted} />
      </div>
      {missing.length > 0 ? (
        <div style={{ fontSize: 12, color: colors.red }}>[MISSING] {missing.join(" · ")}</div>
      ) : null}
      <pre
        style={{
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontSize: 13,
          lineHeight: 1.55,
          maxHeight: 420,
          overflowY: "auto",
          color: run.final_answer ? colors.text : colors.muted,
        }}
      >
        {run.final_answer || "(the supervisor has not produced a final answer yet)"}
      </pre>
    </div>
  );
}