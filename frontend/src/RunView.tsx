import { useEffect, useState } from "react";
import { AgentTree } from "./AgentTree";
import { BudgetBar } from "./BudgetBar";
import { FinalPanel, Pill } from "./FinalPanel";
import { SlotTable } from "./SlotTable";
import { colors, mutedStyle, panelStyle, statusColor } from "./theme";
import { isTerminal, type RunSummary } from "./types";
import type { StreamState } from "./useRunStream";

type DebugPatch = {
  budget_tokens?: number;
  max_depth?: number;
  max_concurrency?: number;
  fail_next?: boolean;
};

type RunViewProps = {
  run: RunSummary | null;
  streamState: StreamState;
  busy: boolean;
  actionError: string | null;
  onCancel: () => void;
  onResume: (extraBudgetTokens: number) => void;
  onReconnect: () => void;
  onPatchDebug: (body: DebugPatch) => Promise<void>;
};

const numberStyle = {
  width: 84,
  background: colors.bg,
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  color: colors.text,
  padding: "3px 6px",
  fontSize: 12,
} as const;

const buttonStyle = {
  background: colors.panelAlt,
  color: colors.text,
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  padding: "5px 12px",
  cursor: "pointer",
  fontSize: 12,
} as const;

export function RunView({
  run,
  streamState,
  busy,
  actionError,
  onCancel,
  onResume,
  onReconnect,
  onPatchDebug,
}: RunViewProps) {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [extraBudget, setExtraBudget] = useState(20000);
  const [debugBudget, setDebugBudget] = useState(0);
  const [debugDepth, setDebugDepth] = useState(0);
  const [debugConcurrency, setDebugConcurrency] = useState(1);

  useEffect(() => {
    setSelectedAgent(null);
    setDebugBudget(run?.budget_tokens ?? 0);
    setDebugDepth(run?.max_depth ?? 0);
    setDebugConcurrency(run?.max_concurrency ?? 1);
  }, [run?.run_id]);

  if (!run) {
    return (
      <section style={panelStyle}>
        <div style={mutedStyle}>select a run or create one</div>
      </section>
    );
  }

  const active = run.status === "queued" || run.status === "running";
  const resumable = ["failed", "interrupted", "cancelled", "budget_exhausted"].includes(run.status);
  const selected = run.agents.find((agent) => agent.id === selectedAgent) ?? null;

  return (
    <div>
      <section style={panelStyle}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <strong style={{ fontSize: 15 }}>{run.run_id}</strong>
          <Pill label={`run ${run.status}`} color={statusColor(run.status)} />
          <span style={{ ...mutedStyle, fontSize: 12 }}>
            stream: {streamState}
            {isTerminal(run.status) ? " (closed)" : ""}
          </span>
          <button
            style={{ ...buttonStyle, padding: "1px 8px", fontSize: 11 }}
            onClick={onReconnect}
          >
            reconnect
          </button>
          <span style={{ display: "flex", gap: 8, marginLeft: "auto", alignItems: "center" }}>
            {active ? (
              <button style={buttonStyle} onClick={onCancel} disabled={busy}>
                cancel run
              </button>
            ) : null}
            {resumable ? (
              <>
                <input
                  type="number"
                  min={10000}
                  step={10000}
                  value={extraBudget}
                  onChange={(event) => setExtraBudget(Number(event.target.value))}
                  title="extra budget tokens added on resume"
                  style={{
                    width: 92,
                    background: colors.bg,
                    border: `1px solid ${colors.border}`,
                    borderRadius: 6,
                    color: colors.text,
                    padding: "4px 6px",
                    fontSize: 12,
                  }}
                />
                <button style={buttonStyle} onClick={() => onResume(extraBudget)} disabled={busy}>
                  resume (+tokens)
                </button>
              </>
            ) : null}
          </span>
        </div>
        <div style={{ ...mutedStyle, fontSize: 12, margin: "6px 0 10px" }}>{run.task}</div>
        <BudgetBar run={run} />
        {active ? (
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "wrap",
              fontSize: 12,
              marginTop: 8,
            }}
          >
            <span style={mutedStyle}>debug:</span>
            <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
              budget
              <input
                type="number"
                min={10000}
                step={10000}
                value={debugBudget}
                onChange={(event) => setDebugBudget(Number(event.target.value))}
                style={numberStyle}
              />
            </label>
            <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
              depth
              <input
                type="number"
                min={0}
                max={3}
                value={debugDepth}
                onChange={(event) => setDebugDepth(Number(event.target.value))}
                style={numberStyle}
              />
            </label>
            <label style={{ display: "flex", gap: 4, alignItems: "center" }}>
              concurrency
              <input
                type="number"
                min={1}
                max={6}
                value={debugConcurrency}
                onChange={(event) => setDebugConcurrency(Number(event.target.value))}
                style={numberStyle}
              />
            </label>
            <button
              style={{ ...buttonStyle, padding: "1px 8px", fontSize: 11 }}
              disabled={busy}
              onClick={() =>
                onPatchDebug({
                  budget_tokens: debugBudget,
                  max_depth: debugDepth,
                  max_concurrency: debugConcurrency,
                })
              }
            >
              apply
            </button>
            <button
              style={{ ...buttonStyle, padding: "1px 8px", fontSize: 11 }}
              disabled={busy}
              title="the next spawned sub-agent fails right after spawn"
              onClick={() => onPatchDebug({ fail_next: true })}
            >
              fail next agent
            </button>
            {run.debug["fail_next"] ? (
              <span style={{ color: colors.amber }}>failure armed</span>
            ) : null}
          </div>
        ) : null}
        {actionError ? (
          <div style={{ color: colors.red, fontSize: 12, marginTop: 8 }}>{actionError}</div>
        ) : null}
        {Object.keys(run.debug).length > 0 ? (
          <div style={{ ...mutedStyle, fontSize: 11, marginTop: 6 }}>
            debug: {JSON.stringify(run.debug)}
          </div>
        ) : null}
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 12 }}>
        <section style={panelStyle}>
          <div style={{ marginBottom: 8, fontWeight: 600 }}>Agent tree</div>
          <AgentTree agents={run.agents} selectedId={selectedAgent} onSelect={setSelectedAgent} />
          {selected ? (
            <div
              style={{
                marginTop: 10,
                borderTop: `1px solid ${colors.border}`,
                paddingTop: 8,
                fontSize: 12,
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <div>
                <strong>{selected.id}</strong> {selected.role} · depth {selected.depth} ·{" "}
                {selected.status}
                {selected.error_kind ? ` · ${selected.error_kind}` : ""}
              </div>
              <div style={mutedStyle}>task: {selected.task}</div>
              {selected.summary ? <div>summary: {selected.summary}</div> : null}
            </div>
          ) : null}
        </section>

        <section style={panelStyle}>
          <div style={{ marginBottom: 8, fontWeight: 600 }}>Artifacts</div>
          <SlotTable slots={run.slots} />
        </section>
      </div>

      <section style={panelStyle}>
        <div style={{ marginBottom: 8, fontWeight: 600 }}>Final answer</div>
        <FinalPanel run={run} />
      </section>
    </div>
  );
}