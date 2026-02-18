import { useStore } from "../store";
import { AgentCard } from "./AgentCard";

export function LeftPanel() {
  const connected = useStore((s) => s.connected);
  const status = useStore((s) => s.status);
  const cwd = useStore((s) => s.cwd);
  const agents = useStore((s) => s.agents);
  const filterAgentId = useStore((s) => s.filterAgentId);
  const setFilterAgent = useStore((s) => s.setFilterAgent);
  const thinkingPhase = useStore((s) => s.thinkingPhase);
  const thinkingDetail = useStore((s) => s.thinkingDetail);

  return (
    <div className="panel">
      <div className="panel-header">
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            className={`connection-dot ${connected ? "connected" : "disconnected"}`}
          />
          Claude Dashboard
        </div>
      </div>

      <div className="panel-body">
        {/* Status */}
        <div style={{ marginBottom: 16 }}>
          <div
            style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              marginBottom: 4,
            }}
          >
            STATUS
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
            }}
          >
            {status === "idle" && (
              <span style={{ color: "var(--text-secondary)" }}>Idle</span>
            )}
            {status === "thinking" && (
              <div>
                <span style={{ color: "var(--accent)" }}>
                  Thinking
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </span>
                {thinkingDetail && (
                  <div
                    className="fade-in"
                    style={{
                      fontSize: 11,
                      color: "var(--text-secondary)",
                      marginTop: 2,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {thinkingDetail}
                  </div>
                )}
              </div>
            )}
            {status === "executing" && (
              <div>
                <span style={{ color: "var(--green)" }}>Executing</span>
                {thinkingPhase && thinkingDetail && (
                  <div
                    className="fade-in"
                    style={{
                      fontSize: 11,
                      color: "var(--text-secondary)",
                      marginTop: 2,
                      fontFamily: "var(--font-mono)",
                    }}
                  >
                    {thinkingDetail}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Working directory */}
        {cwd && (
          <div style={{ marginBottom: 16 }}>
            <div
              style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                marginBottom: 4,
              }}
            >
              WORKING DIR
            </div>
            <div
              style={{
                fontSize: 12,
                fontFamily: "var(--font-mono)",
                color: "var(--text-primary)",
                wordBreak: "break-all",
              }}
            >
              {cwd}
            </div>
          </div>
        )}

        {/* Agent roster */}
        <div>
          <div
            style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              marginBottom: 8,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>AGENTS ({agents.length})</span>
            {filterAgentId && (
              <button
                onClick={() => setFilterAgent(null)}
                style={{
                  fontSize: 10,
                  color: "var(--accent)",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  padding: 0,
                  fontFamily: "var(--font)",
                }}
              >
                Clear filter
              </button>
            )}
          </div>
          {agents.length === 0 && (
            <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              No agents spawned yet
            </div>
          )}
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      </div>
    </div>
  );
}
