import type { TimelineEvent } from "../../../shared/src/types";
import { getToolColor } from "../lib/colors";
import { formatDuration } from "../lib/format";
import { useState } from "react";

type Props = {
  event: TimelineEvent;
};

export function TimelineNode({ event }: Props) {
  const [hovered, setHovered] = useState(false);
  const color =
    event.tool ? getToolColor(event.tool) : "var(--text-secondary)";
  const isActive = event.status === "active";

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        flexShrink: 0,
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Node circle */}
      <div
        className={isActive ? "pulse-glow" : "fade-in"}
        style={{
          width: 14,
          height: 14,
          borderRadius: "50%",
          background: isActive
            ? color
            : `color-mix(in srgb, ${color} 60%, transparent)`,
          border: `2px solid ${color}`,
          color,
          transition: "var(--transition)",
          cursor: "pointer",
        }}
      />

      {/* Label below */}
      <div
        style={{
          fontSize: 9,
          color: "var(--text-secondary)",
          marginTop: 4,
          fontFamily: "var(--font-mono)",
          maxWidth: 60,
          textAlign: "center",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {event.tool || event.type}
      </div>

      {/* Tooltip on hover */}
      {hovered && (
        <div
          style={{
            position: "absolute",
            top: -44,
            left: "50%",
            transform: "translateX(-50%)",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "6px 10px",
            fontSize: 11,
            whiteSpace: "nowrap",
            zIndex: 10,
            boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ fontWeight: 500 }}>{event.label}</div>
          {event.duration !== undefined && (
            <div style={{ color: "var(--text-secondary)", fontSize: 10 }}>
              {formatDuration(event.duration)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
