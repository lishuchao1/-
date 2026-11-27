import { useEffect, useState } from "react";
import { createRun, getFailureMode, setFailureMode } from "./api";
import { colors, mutedStyle, statusColor, yuan } from "./theme";
import type { FailureMode, RunListItem } from "./types";

const fieldStyle = {
  background: colors.bg,
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  color: colors.text,
  padding: "4px 8px",
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

export function NewRunForm({ onCreated }: { onCreated: (runId: string) => void }) {
  const [task, setTask] = useState(
    "Draft a one-page launch brief for a tower defense mobile game: positioning, three milestones and one risk per milestone.",
  );
  const [budget, setBudget] = useState(120000);
  const [depth, setDepth] = useState(2);
  const [concurrency, setConcurrency] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await createRun({
        task: task.trim(),
        budget_tokens: budget,
        max_depth: depth,
        max_concurrency: concurrency,
      });
      onCreated(created.run_id);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontWeight: 600 }}>New run</div>
      <textarea
        value={task}
        onChange={(event) => setTask(event.target.value)}
        rows={4}
        style={{ ...fieldStyle, resize: "vertical", lineHeight: 1.4 }}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <label style={{ flex: 1, fontSize: 11, ...mutedStyle }}>
          budget
          <input
            type="number"
            value={budget}
            min={10000}
            step={10000}
            onChange={(event) => setBudget(Number(event.target.value))}
            style={{ ...fieldStyle, width: "100%", marginTop: 2 }}
          />
        </label>
        <label style={{ flex: 1, fontSize: 11, ...mutedStyle }}>
          max depth
          <input
            type="number"
            value={depth}
            min={0}
            max={3}
            onChange={(event) => setDepth(Number(event.target.value))}
            style={{ ...fieldStyle, width: "100%", marginTop: 2 }}
          />
        </label>
        <label style={{ flex: 1, fontSize: 11, ...mutedStyle }}>
          concurrency
          <input
            type="number"
            value={concurrency}
            min={1}
            max={6}
            onChange={(event) => setConcurrency(Number(event.target.value))}
            style={{ ...fieldStyle, width: "100%", marginTop: 2 }}
          />
        </label>
      </div>
      <button style={buttonStyle} onClick={submit} disabled={busy || task.trim().length < 4}>
        {busy ? "starting..." : "start run"}
      </button>
      {error ? <div style={{ color: colors.red, fontSize: 11 }}>{error}</div> : null}
    </div>
  );
}

export function RunList({
  runs,
  selected,
  onSelect,
}: {
  runs: RunListItem[];
  selected: string | null;
  onSelect: (runId: string) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontWeight: 600 }}>Runs</div>
      {runs.length === 0 ? <div style={{ ...mutedStyle, fontSize: 12 }}>no runs yet</div> : null}
      {runs.map((run) => (
        <div
          key={run.run_id}
          onClick={() => onSelect(run.run_id)}
          style={{
            cursor: "pointer",
            padding: "5px 8px",
            borderRadius: 6,
            border: `1px solid ${selected === run.run_id ? colors.blue : colors.border}`,
            background: selected === run.run_id ? colors.panelAlt : "transparent",
            fontSize: 12,
          }}
        >
          <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
            <span style={{ color: statusColor(run.status) }}>●</span>
            <strong>{run.run_id}</strong>
            <span style={{ color: statusColor(run.status), fontSize: 11 }}>{run.status}</span>
            <span style={{ ...mutedStyle, marginLeft: "auto", fontSize: 10 }}>
              {run.tokens_used.toLocaleString()} tok · {yuan(run.cost)}
            </span>
          </div>
          <div style={{ ...mutedStyle, fontSize: 11, marginTop: 2 }}>
            {run.task.length > 64 ? `${run.task.slice(0, 64)}…` : run.task}
          </div>
        </div>
      ))}
    </div>
  );
}

const MODES: FailureMode[] = ["off", "transient", "permanent", "structural", "task"];

export function FaultControl() {
  const [mode, setMode] = useState<FailureMode>("off");
  const [calls, setCalls] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getFailureMode()
      .then((snapshot) => {
        setMode(snapshot.mode);
        setStatus(`current: ${snapshot.mode}${snapshot.remaining === null ? " (unlimited)" : ""}`);
      })
      .catch(() => setStatus("unavailable"));
  }, []);

  const apply = async () => {
    setBusy(true);
    try {
      const snapshot = await setFailureMode(mode, calls.trim() === "" ? null : Number(calls));
      setStatus(`current: ${snapshot.mode} · remaining ${snapshot.remaining ?? "unlimited"}`);
    } catch (err) {
      setStatus(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontWeight: 600 }}>Fault injection</div>
      <div style={{ display: "flex", gap: 6 }}>
        <select
          value={mode}
          onChange={(event) => setMode(event.target.value as FailureMode)}
          style={{ ...fieldStyle, flex: 1 }}
        >
          {MODES.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <input
          value={calls}
          onChange={(event) => setCalls(event.target.value)}
          placeholder="calls"
          style={{ ...fieldStyle, width: 64 }}
        />
        <button style={buttonStyle} onClick={apply} disabled={busy}>
          apply
        </button>
      </div>
      <div style={{ ...mutedStyle, fontSize: 11 }}>{status}</div>
      <div style={{ ...mutedStyle, fontSize: 11 }}>
        transient = retry once then recover · permanent = every attempt fails · structural = config
        error without retry · task = one task-level 400 then a narrowed retry · empty calls = mode
        default
      </div>
    </div>
  );
}