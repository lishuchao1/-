import { useEffect, useState } from "react";
import { fetchHealth } from "./api";
import TickPanel from "./TickPanel";
import type { Health } from "./types";

const styles = {
  page: { padding: 16, lineHeight: 1.5 } as const,
  header: { display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 } as const,
  ok: { color: "#6ee7a8" } as const,
  bad: { color: "#f87171" } as const,
  panel: {
    border: "1px solid #2a2f37",
    borderRadius: 6,
    padding: 10,
    marginBottom: 10,
  } as const,
  muted: { color: "#8b95a3" } as const,
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((err: unknown) => setError(String(err)));
  }, []);

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <strong>Super-Agent Orchestration Demo</strong>
        {error ? (
          <span style={styles.bad}>backend unreachable</span>
        ) : health ? (
          <span style={styles.ok}>backend ok</span>
        ) : (
          <span style={styles.muted}>connecting...</span>
        )}
      </div>

      <div style={styles.panel}>
        <div>provider: {health?.provider ?? "-"}</div>
        <div>supervisor model: {health?.model_main ?? "-"}</div>
        <div>sub-agent model: {health?.model_sub ?? "-"}</div>
        <div>fallback configured: {String(health?.fallback_configured ?? false)}</div>
        {error ? <div style={styles.bad}>{error}</div> : null}
      </div>

      <TickPanel />

      <div style={styles.panel}>
        <div style={styles.muted}>tree / transcript / debug panels land in later commits</div>
      </div>
    </div>
  );
}