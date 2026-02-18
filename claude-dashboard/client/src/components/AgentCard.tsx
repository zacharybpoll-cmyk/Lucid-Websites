import type { AgentInfo } from "../../../shared/src/types";
import { formatDuration } from "../lib/format";
import { useStore } from "../store";

type Props = {
  agent: AgentInfo;
};

export function AgentCard({ agent }: Props) {
  const filterAgentId = useStore((s) => s.filterAgentId);
  const setFilterAgent = useStore((s) => s.setFilterAgent);
  const isFiltered = filterAgentId === agent.id;
  const isActive = agent.status === "active";

  return (
    <div
      className="slide-in-left"
      onClick={() => setFilterAgent(isFiltered ? null : agent.id)}
      style={{
        padding: "10px 12px",
        borderRadius: "var(--radius)",
        background: isFiltered ? "var(--surface-hover)" : "var(--surface)",
        border: `1px solid ${isFiltered ? "var(--accent)" : "var(--border)"}`,
        cursor: "pointer",
        transition: "var(--transition)",
        marginBottom: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div
          className={isActive ? "pulse-glow" : ""}
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: isActive ? "var(--green)" : "var(--text-secondary)",
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 13,
            fontWeight: 500,
            color: "var(--text-primary)",
          }}
        >
          {agent.type}
        </span>
        {!isActive && agent.endTime && (
          <span
            style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              marginLeft: "auto",
            }}
          >
            {formatDuration(agent.endTime - agent.spawnTime)}
          </span>
        )}
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-secondary)",
          marginTop: 4,
          lineHeight: 1.4,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {agent.description}
      </div>
    </div>
  );
}
