import { useEffect, useState } from "react";
import { fetchAgentConversation } from "./api";
import { AgentTree } from "./AgentTree";
import { BudgetBar } from "./BudgetBar";
import { FinalPanel, Pill } from "./FinalPanel";
import { SlotTable } from "./SlotTable";
import { colors, mutedStyle, panelStyle, statusColor } from "./theme";
import { isTerminal, type AgentConversation, type ConversationMessage, type RunSummary } from "./types";
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

const preStyle = {
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  background: colors.bg,
  border: `1px solid ${colors.border}`,
  borderRadius: 6,
  padding: 8,
  margin: "4px 0 0",
  fontSize: 11,
  maxHeight: 260,
  overflow: "auto",
} as const;

function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

function roleColor(role: ConversationMessage["role"]): string {
  if (role === "system") return colors.purple;
  if (role === "assistant") return colors.blue;
  if (role === "tool") return colors.cyan;
  return colors.amber;
}

function MessageRow({ message, index }: { message: ConversationMessage; index: number }) {
  const body = message.content ?? "";
  return (
    <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: 8, marginTop: 8 }}>
      <div style={{ fontSize: 11, color: colors.muted }}>
        #{index + 1} <span style={{ color: roleColor(message.role) }}>{message.role}</span>
        {message.tool_call_id ? ` · ${message.tool_call_id}` : ""}
      </div>
      {message.reasoning_content ? (
        <details style={{ marginTop: 4 }}>
          <summary style={{ ...mutedStyle, fontSize: 11, cursor: "pointer" }}>
            thinking ({message.reasoning_content.length} chars)
          </summary>
          <pre style={preStyle}>{message.reasoning_content}</pre>
        </details>
      ) : null}
      {body ? (
        message.role === "system" ? (
          <details style={{ marginTop: 4 }}>
            <summary style={{ ...mutedStyle, fontSize: 11, cursor: "pointer" }}>
              system prompt ({body.length} chars)
            </summary>
            <pre style={preStyle}>{body}</pre>
          </details>
        ) : (
          <pre style={preStyle}>{body}</pre>
        )
      ) : null}
      {message.tool_calls?.map((call) => (
        <div key={call.id} style={{ marginTop: 6 }}>
          <div style={{ fontSize: 12 }}>
            tool call · <strong>{call.function.name}</strong> · <span style={mutedStyle}>{call.id}</span>
          </div>
          <pre style={preStyle}>{prettyJson(call.function.arguments)}</pre>
        </div>
      ))}
    </div>
  );
}

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
  const [conversation, setConversation] = useState<AgentConversation | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);
  const selectedAgentStatus = run?.agents.find((agent) => agent.id === selectedAgent)?.status;

  useEffect(() => {
    setSelectedAgent(null);
    setDebugBudget(run?.budget_tokens ?? 0);
    setDebugDepth(run?.max_depth ?? 0);
    setDebugConcurrency(run?.max_concurrency ?? 1);
  }, [run?.run_id]);

  useEffect(() => {
    setConversation(null);
    setConversationError(null);
    if (!run?.run_id || !selectedAgent) return;
    let stopped = false;
    let timer: number | undefined;
    const load = async () => {
      try {
        const data = await fetchAgentConversation(run.run_id, selectedAgent);
        if (stopped) return;
        setConversation(data);
        if (data.status === "queued" || data.status === "running") {
          timer = window.setTimeout(load, 1500);
        }
      } catch (error) {
        if (stopped) return;
        setConversationError(error instanceof Error ? error.message : String(error));
      }
    };
    load();
    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [run?.run_id, selectedAgent, selectedAgentStatus]);

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
          <SlotTable slots={run.slots} showMissing={isTerminal(run.status)} />
        </section>
      </div>

      <section style={panelStyle}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          <strong>Conversation</strong>
          {selected ? (
            <span style={{ fontSize: 12 }}>
              <strong>{selected.id}</strong> {selected.role} · depth {selected.depth} · {selected.status}
            </span>
          ) : (
            <span style={mutedStyle}>select a node in the tree to see exactly what that agent could see</span>
          )}
        </div>
        {selected ? (
          <>
            <div style={{ ...mutedStyle, fontSize: 11, marginBottom: 4 }}>
              {selected.depth === 0
                ? "Supervisor: its system prompt, the user task and its own tool round trips. Sub-agent conversations are not in its context."
                : "Sub-agent: only its own system prompt, assignment, supervisor-provided context and its own tool round trips. The supervisor's conversation and sibling agents are not in this context."}
            </div>
            {conversationError ? (
              <div style={{ color: colors.red, fontSize: 12 }}>{conversationError}</div>
            ) : null}
            {!conversation && !conversationError ? (
              <div style={{ ...mutedStyle, fontSize: 12 }}>loading conversation…</div>
            ) : null}
            {conversation && conversation.messages.length === 0 ? (
              <div style={{ ...mutedStyle, fontSize: 12 }}>no transcript recorded for this agent</div>
            ) : null}
            {conversation?.messages.map((message, index) => (
              <MessageRow key={index} message={message} index={index} />
            ))}
          </>
        ) : null}
      </section>

      <section style={panelStyle}>
        <div style={{ marginBottom: 8, fontWeight: 600 }}>Final answer</div>
        <FinalPanel run={run} />
      </section>
    </div>
  );
}