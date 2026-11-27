import { colors, mutedStyle } from "./theme";
import { missingSlots, type ArtifactSlot } from "./types";

export function SlotTable({ slots, showMissing }: { slots: ArtifactSlot[]; showMissing: boolean }) {
  const missing = showMissing ? missingSlots(slots) : [];
  if (slots.length === 0 && missing.length === 0) {
    return <div style={mutedStyle}>no artifacts written yet</div>;
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr style={{ color: colors.muted, textAlign: "left" }}>
          <th style={{ padding: "2px 6px" }}>key</th>
          <th style={{ padding: "2px 6px" }}>status</th>
          <th style={{ padding: "2px 6px" }}>version</th>
          <th style={{ padding: "2px 6px" }}>chars</th>
          <th style={{ padding: "2px 6px" }}>last writer</th>
        </tr>
      </thead>
      <tbody>
        {slots.map((slot) => (
          <tr key={slot.key} style={{ borderTop: `1px solid ${colors.border}` }}>
            <td style={{ padding: "3px 6px", color: colors.purple }}>{slot.key}</td>
            <td style={{ padding: "3px 6px", color: slot.status === "filled" ? colors.green : colors.red }}>
              {slot.status}
            </td>
            <td style={{ padding: "3px 6px" }}>v{slot.version}</td>
            <td style={{ padding: "3px 6px" }}>{slot.chars}</td>
            <td style={{ padding: "3px 6px", color: colors.muted }}>{slot.last_agent ?? "-"}</td>
          </tr>
        ))}
        {missing.map((key) => (
          <tr key={`missing-${key}`} style={{ borderTop: `1px solid ${colors.border}` }}>
            <td style={{ padding: "3px 6px", color: colors.purple }}>{key}</td>
            <td style={{ padding: "3px 6px", color: colors.red }}>[MISSING]</td>
            <td style={{ padding: "3px 6px", color: colors.muted }}>-</td>
            <td style={{ padding: "3px 6px", color: colors.muted }}>-</td>
            <td style={{ padding: "3px 6px", color: colors.muted }}>-</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}