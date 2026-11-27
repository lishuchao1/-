import { useEffect, useMemo, useRef, useState } from "react";
import { colors, eventColor, mutedStyle, timeOf } from "./theme";
import type { RunEvent } from "./types";

function EventRow({ event }: { event: RunEvent }) {
  const data = event.data ?? {};
  const hasData = Object.keys(data).length > 0;
  const tokens = (event.tokens_in ?? 0) + (event.tokens_out ?? 0);
  return (
    <details style={{ borderBottom: `1px solid ${colors.border}`, padding: "1px 0" }}>
      <summary
        style={{
          cursor: "pointer",
          listStyle: "none",
          display: "flex",
          gap: 8,
          alignItems: "baseline",
          whiteSpace: "nowrap",
        }}
      >
        <span style={{ color: colors.muted, width: 40 }}>#{event.id}</span>
        <span style={{ color: colors.muted, width: 68 }}>{timeOf(event.ts)}</span>
        <span style={{ color: eventColor(event.kind), width: 132, overflow: "hidden", textOverflow: "ellipsis" }}>
          {event.kind}
        </span>
        <span style={{ color: colors.blue, width: 34 }}>{event.agent_id}</span>
        <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{event.summary}</span>
        {tokens > 0 ? <span style={{ color: colors.muted }}>{tokens} tok</span> : null}
      </summary>
      {hasData ? (
        <pre
          style={{
            margin: "4px 0 6px 44px",
            padding: 6,
            background: colors.panelAlt,
            borderRadius: 4,
            color: colors.muted,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      ) : null}
    </details>
  );
}

export function EventLog({ events }: { events: RunEvent[] }) {
  const [filter, setFilter] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return events;
    return events.filter((event) =>
      [event.kind, event.agent_id ?? "", event.summary ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [events, filter]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [visible.length]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="filter by kind, agent or text"
          style={{
            flex: 1,
            background: colors.bg,
            border: `1px solid ${colors.border}`,
            borderRadius: 6,
            color: colors.text,
            padding: "4px 8px",
            fontSize: 12,
          }}
        />
        <span style={{ ...mutedStyle, fontSize: 12 }}>
          {visible.length}/{events.length} events
        </span>
      </div>
      <div style={{ overflowY: "auto", maxHeight: 460, fontFamily: "Consolas, monospace", fontSize: 12 }}>
        {visible.map((event) => (
          <EventRow key={event.id} event={event} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}