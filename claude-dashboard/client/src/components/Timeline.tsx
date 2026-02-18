import { useRef, useEffect } from "react";
import { useStore } from "../store";
import { TimelineNode } from "./TimelineNode";

export function Timeline() {
  const events = useStore((s) => s.timelineEvents);
  const filterAgentId = useStore((s) => s.filterAgentId);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the right as events arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [events.length]);

  // Split into main events and agent events
  const mainEvents = events.filter(
    (e) =>
      !e.agentId && (!filterAgentId || filterAgentId === null)
  );

  const agentGroups = new Map<string, typeof events>();
  events.forEach((e) => {
    if (e.agentId) {
      if (!agentGroups.has(e.agentId)) {
        agentGroups.set(e.agentId, []);
      }
      agentGroups.get(e.agentId)!.push(e);
    }
  });

  const filteredMainEvents = filterAgentId
    ? events.filter((e) => !e.agentId || e.agentId === filterAgentId)
    : events.filter((e) => !e.agentId);

  const filteredAgentGroups = filterAgentId
    ? new Map([[filterAgentId, agentGroups.get(filterAgentId) || []]])
    : agentGroups;

  if (events.length === 0) {
    return (
      <div
        style={{
          padding: "20px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-secondary)",
          fontSize: 12,
          height: 80,
        }}
      >
        Timeline will populate as tools are called
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      style={{
        overflowX: "auto",
        overflowY: "hidden",
        padding: "16px",
        minHeight: 80,
      }}
    >
      {/* Main timeline row */}
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {filteredMainEvents.map((event, i) => (
          <div key={event.id} style={{ display: "flex", alignItems: "center" }}>
            <TimelineNode event={event} />
            {i < filteredMainEvents.length - 1 && (
              <div
                style={{
                  width: 20,
                  height: 2,
                  background: "var(--border)",
                  margin: "0 2px",
                  marginBottom: 16,
                }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Agent branch rows */}
      {[...filteredAgentGroups.entries()].map(([agentId, agentEvents]) => {
        if (agentEvents.length === 0) return null;
        return (
          <div
            key={agentId}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              marginTop: 8,
              paddingLeft: 24,
              borderLeft: "2px solid var(--purple)",
              marginLeft: 6,
            }}
          >
            <div
              style={{
                fontSize: 9,
                color: "var(--purple)",
                fontFamily: "var(--font-mono)",
                marginRight: 8,
                flexShrink: 0,
              }}
            >
              sub
            </div>
            {agentEvents.map((event, i) => (
              <div
                key={event.id}
                style={{ display: "flex", alignItems: "center" }}
              >
                <TimelineNode event={event} />
                {i < agentEvents.length - 1 && (
                  <div
                    style={{
                      width: 16,
                      height: 2,
                      background: "var(--border)",
                      margin: "0 2px",
                      marginBottom: 16,
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
