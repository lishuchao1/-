import { useCallback, useEffect, useState } from "react";
import { cancelRun, fetchHealth, listRuns, resumeRun } from "./api";
import { EventLog } from "./EventLog";
import { RunView } from "./RunView";
import { FaultControl, NewRunForm, RunList } from "./Sidebar";
import TickPanel from "./TickPanel";
import { colors, mutedStyle, panelStyle } from "./theme";
import type { Health, RunListItem } from "./types";
import { useRunStream } from "./useRunStream";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const { run, events, streamState } = useRunStream(selected, epoch);

  const refreshRuns = useCallback(async () => {
    try {
      const data = await listRuns();
      setRuns(data.runs);
    } catch {
      // backend may still be starting
    }
  }, []);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    refreshRuns();
    const timer = window.setInterval(refreshRuns, 3000);
    return () => window.clearInterval(timer);
  }, [refreshRuns]);

  useEffect(() => {
    if (!selected && runs.length > 0) {
      setSelected(runs[0].run_id);
    }
  }, [runs, selected]);

  const selectRun = (runId: string) => {
    setSelected(runId);
    setActionError(null);
    setEpoch((value) => value + 1);
  };

  const handleCreated = (runId: string) => {
    selectRun(runId);
    refreshRuns();
  };

  const handleCancel = async () => {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      await cancelRun(selected);
      await refreshRuns();
      setEpoch((value) => value + 1);
    } catch (err) {
      setActionError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleResume = async (extraBudgetTokens: number) => {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      await resumeRun(selected, extraBudgetTokens || undefined);
      await refreshRuns();
      setEpoch((value) => value + 1);
    } catch (err) {
      setActionError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: colors.bg,
        color: colors.text,
        padding: 16,
        fontFamily: "system-ui, Segoe UI, sans-serif",
      }}
    >
      <header style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <strong style={{ fontSize: 16 }}>Super-Agent Orchestration Demo</strong>
        {health ? (
          <span style={{ color: colors.green, fontSize: 12 }}>
            backend ok · {health.model_main} / {health.model_sub} · fault injection{" "}
            {health.failure_inject_mode}
          </span>
        ) : (
          <span style={{ color: colors.red, fontSize: 12 }}>backend unreachable</span>
        )}
        <span style={{ ...mutedStyle, fontSize: 12, marginLeft: "auto" }}>
          supervisor plans at runtime · sub-agents have isolated context · artifacts are the only
          channel back
        </span>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0, 1fr)", gap: 12 }}>
        <aside>
          <section style={panelStyle}>
            <NewRunForm onCreated={handleCreated} />
          </section>
          <section style={panelStyle}>
            <RunList runs={runs} selected={selected} onSelect={selectRun} />
          </section>
          <section style={panelStyle}>
            <FaultControl />
          </section>
          <section style={panelStyle}>
            <TickPanel />
          </section>
        </aside>

        <main>
          <RunView
            run={run}
            streamState={streamState}
            busy={busy}
            actionError={actionError}
            onCancel={handleCancel}
            onResume={handleResume}
            onReconnect={() => setEpoch((value) => value + 1)}
          />
          <section style={panelStyle}>
            <div style={{ marginBottom: 8, fontWeight: 600 }}>Event transcript</div>
            <EventLog events={events} />
          </section>
        </main>
      </div>
    </div>
  );
}