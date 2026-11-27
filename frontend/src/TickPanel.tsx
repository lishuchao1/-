import { useEffect, useRef, useState } from "react";
import type { TickEvent } from "./types";

type StreamState = "connecting" | "open" | "error" | "closed";

const MAX_ROWS = 8;

export default function TickPanel() {
  const [state, setState] = useState<StreamState>("connecting");
  const [ticks, setTicks] = useState<TickEvent[]>([]);
  const [replayed, setReplayed] = useState(0);
  const [lastId, setLastId] = useState<number | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const lastIdRef = useRef<number | null>(null);
  const seenRef = useRef<Set<number>>(new Set());
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const resumeFrom = lastIdRef.current;
    const url = resumeFrom === null ? "/api/tick" : `/api/tick?last_event_id=${resumeFrom}`;
    const source = new EventSource(url);
    sourceRef.current = source;
    setState("connecting");
    source.onopen = () => setState("open");
    source.onerror = () => setState(source.readyState === EventSource.CLOSED ? "closed" : "error");
    source.addEventListener("tick", (raw) => {
      const message = raw as MessageEvent<string>;
      const payload = JSON.parse(message.data) as TickEvent;
      if (seenRef.current.has(payload.seq)) {
        return;
      }
      seenRef.current.add(payload.seq);
      lastIdRef.current = Number(message.lastEventId);
      setLastId(Number(message.lastEventId));
      if (payload.replayed) {
        setReplayed((count) => count + 1);
        return;
      }
      setTicks((rows) => [payload, ...rows].slice(0, MAX_ROWS));
    });
    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [generation]);

  const reconnect = () => {
    sourceRef.current?.close();
    setReplayed(0);
    setGeneration((value) => value + 1);
  };

  const badgeColor = state === "open" ? "#2f9e44" : state === "error" ? "#e8590c" : "#868e96";

  return (
    <section style={{ border: "1px solid #2b2b2b", borderRadius: 8, padding: 16, marginTop: 16 }}>
      <header style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <h2 style={{ fontSize: 15, margin: 0 }}>event stream</h2>
        <span style={{ color: badgeColor, fontSize: 12 }}>● {state}</span>
        <span style={{ color: "#868e96", fontSize: 12 }}>last id: {lastId ?? "-"}</span>
        <span style={{ color: "#868e96", fontSize: 12 }}>replayed: {replayed}</span>
        <button
          onClick={reconnect}
          style={{
            marginLeft: "auto",
            background: "transparent",
            color: "#ced4da",
            border: "1px solid #495057",
            borderRadius: 4,
            padding: "2px 10px",
            cursor: "pointer",
            fontSize: 12,
          }}
        >
          reconnect
        </button>
      </header>
      {ticks.length === 0 ? (
        <p style={{ color: "#868e96", fontSize: 12, margin: 0 }}>waiting for ticks ...</p>
      ) : (
        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
          <tbody>
            {ticks.map((tick) => (
              <tr key={tick.seq}>
                <td style={{ color: "#868e96", width: 60 }}>#{tick.seq}</td>
                <td style={{ color: "#adb5bd" }}>{tick.ts.toFixed(3)}</td>
                <td style={{ color: "#adb5bd", textAlign: "right" }}>+{tick.uptime_s.toFixed(1)}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p style={{ color: "#495057", fontSize: 11, margin: "10px 0 0" }}>
        reconnect resumes from the last seen id through the query parameter; a dropped connection
        on the live stream resumes through the Last-Event-ID header.
      </p>
    </section>
  );
}