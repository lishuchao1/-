import { colors, mutedStyle, statusColor } from "./theme";
import type { AgentNode } from "./types";

type TreeProps = {
  agents: AgentNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

function TreeNode({
  agent,
  childrenOf,
  selectedId,
  onSelect,
}: {
  agent: AgentNode;
  childrenOf: Map<string, AgentNode[]>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const kids = childrenOf.get(agent.id) ?? [];
  const selected = selectedId === agent.id;
  return (
    <div>
      <div
        onClick={() => onSelect(agent.id)}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          padding: "4px 8px",
          marginLeft: agent.depth * 18,
          borderRadius: 6,
          cursor: "pointer",
          border: `1px solid ${selected ? colors.blue : "transparent"}`,
          background: selected ? colors.panelAlt : "transparent",
        }}
      >
        <span style={{ color: statusColor(agent.status) }}>●</span>
        <span style={{ fontWeight: 600 }}>{agent.id}</span>
        <span>{agent.role}</span>
        <span style={{ color: statusColor(agent.status), fontSize: 12 }}>{agent.status}</span>
        {agent.error_kind ? (
          <span style={{ color: colors.red, fontSize: 12 }}>{agent.error_kind}</span>
        ) : null}
        <span style={{ ...mutedStyle, marginLeft: "auto", fontSize: 12 }}>
          {agent.steps} steps · {agent.tokens_in + agent.tokens_out} tok · {agent.latency_ms} ms
        </span>
      </div>
      {agent.artifact_keys.length > 0 ? (
        <div style={{ marginLeft: agent.depth * 18 + 26, marginBottom: 4 }}>
          {agent.artifact_keys.map((key) => (
            <code
              key={key}
              style={{
                color: colors.purple,
                fontSize: 11,
                border: `1px solid ${colors.border}`,
                borderRadius: 4,
                padding: "0 4px",
                marginRight: 4,
              }}
            >
              {key}
            </code>
          ))}
        </div>
      ) : null}
      {kids.map((child) => (
        <TreeNode
          key={child.id}
          agent={child}
          childrenOf={childrenOf}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

export function AgentTree({ agents, selectedId, onSelect }: TreeProps) {
  const childrenOf = new Map<string, AgentNode[]>();
  const roots: AgentNode[] = [];
  for (const agent of agents) {
    if (!agent.parent_id) {
      roots.push(agent);
      continue;
    }
    const bucket = childrenOf.get(agent.parent_id) ?? [];
    bucket.push(agent);
    childrenOf.set(agent.parent_id, bucket);
  }
  if (roots.length === 0) {
    return <div style={mutedStyle}>no agents yet</div>;
  }
  return (
    <div>
      {roots.map((root) => (
        <TreeNode
          key={root.id}
          agent={root}
          childrenOf={childrenOf}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}