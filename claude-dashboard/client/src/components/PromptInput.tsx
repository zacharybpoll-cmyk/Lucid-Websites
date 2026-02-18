import { useState, useRef, useEffect } from "react";
import { useStore } from "../store";

export function PromptInput() {
  const [text, setText] = useState("");
  const sendPrompt = useStore((s) => s.sendPrompt);
  const cancelQuery = useStore((s) => s.cancelQuery);
  const status = useStore((s) => s.status);
  const connected = useStore((s) => s.connected);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isRunning = status !== "idle";

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 120) + "px";
    }
  }, [text]);

  function handleSubmit() {
    const trimmed = text.trim();
    if (!trimmed || isRunning || !connected) return;
    sendPrompt(trimmed);
    setText("");
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div
      style={{
        padding: "12px 16px",
        display: "flex",
        gap: 8,
        alignItems: "flex-end",
      }}
    >
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          !connected
            ? "Disconnected..."
            : isRunning
              ? "Agent is working..."
              : "Type a prompt..."
        }
        disabled={isRunning || !connected}
        rows={1}
        style={{
          flex: 1,
          resize: "none",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "10px 14px",
          fontSize: 13,
          fontFamily: "var(--font)",
          color: "var(--text-primary)",
          outline: "none",
          transition: "border-color var(--transition)",
          lineHeight: 1.5,
          maxHeight: 120,
        }}
        onFocus={(e) =>
          (e.target.style.borderColor = "var(--accent)")
        }
        onBlur={(e) =>
          (e.target.style.borderColor = "var(--border)")
        }
      />

      {isRunning ? (
        <button
          onClick={cancelQuery}
          style={{
            padding: "10px 16px",
            background: "color-mix(in srgb, var(--red) 15%, transparent)",
            border: "1px solid var(--red)",
            borderRadius: "var(--radius)",
            color: "var(--red)",
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "var(--font)",
            transition: "var(--transition)",
            flexShrink: 0,
          }}
        >
          Cancel
        </button>
      ) : (
        <button
          onClick={handleSubmit}
          disabled={!text.trim() || !connected}
          style={{
            padding: "10px 16px",
            background:
              text.trim() && connected
                ? "var(--accent)"
                : "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            color:
              text.trim() && connected
                ? "#fff"
                : "var(--text-secondary)",
            fontSize: 13,
            fontWeight: 500,
            cursor:
              text.trim() && connected ? "pointer" : "default",
            fontFamily: "var(--font)",
            transition: "var(--transition)",
            flexShrink: 0,
          }}
        >
          Send
        </button>
      )}
    </div>
  );
}
