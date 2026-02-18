import { useEffect, useState } from "react";
import { useStore } from "../store";
import { StatCard } from "./StatCard";
import { Sparkline } from "./Sparkline";
import { getToolColor } from "../lib/colors";
import { formatDuration, formatPath } from "../lib/format";

export function RightPanel() {
  const toolCounts = useStore((s) => s.toolCounts);
  const opsPerMin = useStore((s) => s.opsPerMin);
  const filesTouched = useStore((s) => s.filesTouched);
  const activeAgents = useStore((s) => s.activeAgents);
  const totalCost = useStore((s) => s.totalCost);
  const sessionStartTime = useStore((s) => s.sessionStartTime);
  const status = useStore((s) => s.status);

  // Live session timer
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!sessionStartTime || status === "idle") {
      setElapsed(0);
      return;
    }
    const interval = setInterval(() => {
      setElapsed(Date.now() - sessionStartTime);
    }, 1000);
    return () => clearInterval(interval);
  }, [sessionStartTime, status]);

  // Sort tool counts descending
  const sortedTools = Object.entries(toolCounts).sort(
    ([, a], [, b]) => b - a
  );
  const maxCount = sortedTools.length > 0 ? sortedTools[0][1] : 1;

  const currentOps = opsPerMin.length > 0 ? opsPerMin[opsPerMin.length - 1] : 0;

  return (
    <div className="panel">
      <div className="panel-header">Statistics</div>
      <div className="panel-body">
        {/* Session duration */}
        {elapsed > 0 && (
          <StatCard label="Session Duration" value={formatDuration(elapsed)} />
        )}

        {/* Active agents */}
        <StatCard
          label="Active Agents"
          value={activeAgents}
          color={activeAgents > 0 ? "var(--green)" : undefined}
        />

        {/* Ops per minute */}
        <StatCard label="Ops / Minute" value={currentOps}>
          <div style={{ marginTop: 8 }}>
            <Sparkline data={opsPerMin} width={210} height={36} />
          </div>
        </StatCard>

        {/* Cost */}
        {totalCost > 0 && (
          <StatCard
            label="API Cost"
            value={`$${totalCost.toFixed(4)}`}
            color="var(--orange)"
          />
        )}

        {/* Tool counts */}
        {sortedTools.length > 0 && (
          <div
            style={{
              padding: "10px 12px",
              background: "var(--surface)",
              borderRadius: "var(--radius)",
              border: "1px solid var(--border)",
              marginBottom: 8,
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                marginBottom: 8,
                fontWeight: 500,
              }}
            >
              TOOL CALLS
            </div>
            {sortedTools.map(([tool, count]) => (
              <div
                key={tool}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-secondary)",
                    width: 60,
                    flexShrink: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {tool}
                </span>
                <div
                  style={{
                    flex: 1,
                    height: 6,
                    background: "var(--bg)",
                    borderRadius: 3,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${(count / maxCount) * 100}%`,
                      background: getToolColor(tool),
                      borderRadius: 3,
                      transition: "width 300ms ease-out",
                    }}
                  />
                </div>
                <span
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--font-mono)",
                    color: "var(--text-primary)",
                    width: 24,
                    textAlign: "right",
                    flexShrink: 0,
                  }}
                >
                  {count}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Files touched */}
        {filesTouched.length > 0 && (
          <div
            style={{
              padding: "10px 12px",
              background: "var(--surface)",
              borderRadius: "var(--radius)",
              border: "1px solid var(--border)",
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                marginBottom: 8,
                fontWeight: 500,
              }}
            >
              FILES TOUCHED ({filesTouched.length})
            </div>
            {filesTouched.slice(0, 15).map((f) => (
              <div
                key={f}
                style={{
                  fontSize: 11,
                  fontFamily: "var(--font-mono)",
                  color: "var(--text-primary)",
                  padding: "2px 0",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={f}
              >
                {formatPath(f)}
              </div>
            ))}
            {filesTouched.length > 15 && (
              <div
                style={{
                  fontSize: 10,
                  color: "var(--text-secondary)",
                  marginTop: 4,
                }}
              >
                +{filesTouched.length - 15} more
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
