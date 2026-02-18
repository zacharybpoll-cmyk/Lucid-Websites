import { useRef, useEffect } from "react";
import { useStore } from "../store";
import { ToolIcon } from "./ToolIcon";
import { formatTime } from "../lib/format";

export function ActivityFeed() {
  const entries = useStore((s) => s.feedEntries);
  const streamedText = useStore((s) => s.streamedText);
  const filterAgentId = useStore((s) => s.filterAgentId);
  const scrollRef = useRef<HTMLDivElement>(null);

  const filtered = filterAgentId
    ? entries.filter(
        (e) => !e.agentId || e.agentId === filterAgentId
      )
    : entries;

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered.length, streamedText]);

  return (
    <div
      ref={scrollRef}
      style={{
        height: "100%",
        overflowY: "auto",
        padding: "8px 16px",
      }}
    >
      {filtered.length === 0 && !streamedText && (
        <div
          style={{
            color: "var(--text-secondary)",
            fontSize: 12,
            textAlign: "center",
            paddingTop: 40,
          }}
        >
          Submit a prompt to get started
        </div>
      )}

      {filtered.map((entry) => (
        <div
          key={entry.id}
          className="fade-in-up"
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "6px 0",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--font-mono)",
              color: "var(--text-secondary)",
              flexShrink: 0,
              marginTop: 2,
            }}
          >
            {formatTime(entry.timestamp)}
          </span>

          {entry.tool ? (
            <ToolIcon tool={entry.tool} size={20} />
          ) : (
            <div
              style={{
                width: 20,
                height: 20,
                borderRadius: "var(--radius-sm)",
                background:
                  entry.icon === "error"
                    ? "color-mix(in srgb, var(--red) 15%, transparent)"
                    : "color-mix(in srgb, var(--accent) 15%, transparent)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 10,
                color:
                  entry.icon === "error" ? "var(--red)" : "var(--accent)",
                flexShrink: 0,
              }}
            >
              {entry.icon === "error" ? "!" : "\u2713"}
            </div>
          )}

          <span
            style={{
              fontSize: 12,
              color: "var(--text-primary)",
              lineHeight: 1.5,
              fontFamily:
                entry.text.includes("/") || entry.text.includes(".")
                  ? "var(--font-mono)"
                  : "var(--font)",
            }}
          >
            {entry.text}
          </span>
        </div>
      ))}

      {/* Streamed text output */}
      {streamedText && (
        <div
          style={{
            marginTop: 12,
            padding: "12px",
            background: "var(--surface)",
            borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              marginBottom: 6,
              fontWeight: 600,
            }}
          >
            OUTPUT
          </div>
          <pre
            style={{
              fontSize: 12,
              fontFamily: "var(--font-mono)",
              color: "var(--text-primary)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              lineHeight: 1.6,
              margin: 0,
            }}
          >
            {streamedText}
          </pre>
        </div>
      )}
    </div>
  );
}
