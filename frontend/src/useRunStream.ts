import { useEffect, useRef, useState } from "react";
import { fetchRun, runStreamUrl } from "./api";
import { isTerminal, type RunEvent, type RunSummary } from "./types";

export type StreamState = "connecting" | "live" | "closed" | "retrying";

export function useRunStream(
  runId: string | null,
  epoch = 0,
): {
  run: RunSummary | null;
  events: RunEvent[];
  streamState: StreamState;
} {
  const [run, setRun] = useState<RunSummary | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [streamState, setStreamState] = useState<StreamState>("connecting");
  const lastIdRef = useRef(0);
  const seenRef = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!runId) {
      setRun(null);
      setEvents([]);
      setStreamState("closed");
      return;
    }
    setRun(null);
    setEvents([]);
    setStreamState("connecting");
    lastIdRef.current = 0;
    seenRef.current = new Set();
    let source: EventSource | null = null;
    let stopped = false;
    let finished = false;
    let retryTimer = 0;
    let pollTimer = 0;

    const poll = async () => {
      if (stopped || finished) return;
      try {
        const data = await fetchRun(runId);
        if (stopped) return;
        setRun(data);
        if (isTerminal(data.status)) {
          finished = true;
          window.clearInterval(pollTimer);
        }
      } catch {
        // keep polling; a transient backend error should not stop the UI
      }
    };

    const connect = () => {
      source = new EventSource(runStreamUrl(runId, lastIdRef.current));
      source.addEventListener("open", () => {
        if (!stopped) setStreamState("live");
      });
      source.addEventListener("snapshot", (raw) => {
        const message = raw as MessageEvent<string>;
        const id = Number(message.lastEventId || 0);
        if (id > lastIdRef.current) lastIdRef.current = id;
        try {
          const payload = JSON.parse(message.data) as RunSummary;
          setRun(payload);
          if (isTerminal(payload.status)) {
            // The server replays run_event frames after this snapshot and then
            // closes; closing here would drop the transcript.
            finished = true;
          }
        } catch {
          // ignore malformed frames
        }
      });
      source.addEventListener("run_event", (raw) => {
        const message = raw as MessageEvent<string>;
        try {
          const payload = JSON.parse(message.data) as RunEvent;
          if (seenRef.current.has(payload.id)) return;
          seenRef.current.add(payload.id);
          if (payload.id > lastIdRef.current) lastIdRef.current = payload.id;
          setEvents((previous) => [...previous, payload]);
        } catch {
          // ignore malformed frames
        }
      });
      source.onerror = () => {
        if (stopped) return;
        if (finished) {
          setStreamState("closed");
          source?.close();
          return;
        }
        source?.close();
        setStreamState("retrying");
        retryTimer = window.setTimeout(() => {
          if (!stopped) connect();
        }, 1500);
      };
    };

    connect();
    poll();
    pollTimer = window.setInterval(poll, 2000);
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pollTimer);
      source?.close();
    };
  }, [runId, epoch]);

  return { run, events, streamState };
}