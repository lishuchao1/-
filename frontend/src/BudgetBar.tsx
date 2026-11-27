import { colors, mutedStyle, yuan } from "./theme";
import type { RunSummary } from "./types";

export function BudgetBar({ run }: { run: RunSummary }) {
  const budget = Math.max(1, run.budget_tokens);
  const usedPct = Math.min(100, (run.tokens_used / budget) * 100);
  const reservedPct = Math.min(100 - usedPct, (run.reserved_tokens / budget) * 100);
  const softPct = 90;
  const over = run.tokens_used > budget;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
        <span>
          budget: <strong>{run.tokens_used.toLocaleString()}</strong> /{" "}
          {run.budget_tokens.toLocaleString()} tokens
          {run.reserved_tokens > 0 ? (
            <span style={mutedStyle}> ({run.reserved_tokens.toLocaleString()} reserved)</span>
          ) : null}
        </span>
        <span style={mutedStyle}>
          cost {yuan(run.cost)} · {run.elapsed_s}s
        </span>
      </div>
      <div
        style={{
          position: "relative",
          height: 10,
          borderRadius: 5,
          background: colors.panelAlt,
          border: `1px solid ${colors.border}`,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${usedPct}%`,
            height: "100%",
            background: over || run.budget_hard_stop ? colors.red : usedPct >= softPct ? colors.amber : colors.green,
            transition: "width 0.3s ease",
          }}
        />
        {reservedPct > 0 ? (
          <div
            style={{
              position: "absolute",
              left: `${usedPct}%`,
              width: `${reservedPct}%`,
              height: "100%",
              background: colors.blue,
              opacity: 0.45,
            }}
          />
        ) : null}
        <div
          style={{
            position: "absolute",
            left: `${softPct}%`,
            top: 0,
            width: 1,
            height: "100%",
            background: colors.amber,
            opacity: 0.8,
          }}
        />
      </div>
      <div style={{ ...mutedStyle, fontSize: 11, marginTop: 3 }}>
        green = consumed · blue = reserved by running agents · amber tick = 90% soft limit
        {run.budget_hard_stop ? (
          <span style={{ color: colors.red }}> · hard stop reached</span>
        ) : null}
      </div>
    </div>
  );
}