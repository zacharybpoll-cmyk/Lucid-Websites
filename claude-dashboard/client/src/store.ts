import { create } from "zustand";
import type {
  ServerMessage,
  AgentInfo,
  TimelineEvent,
  FeedEntry,
} from "../../shared/src/types";
import { WsClient } from "./ws-client";

type DashboardState = {
  // Connection
  connected: boolean;
  wsClient: WsClient | null;

  // Session
  sessionId: string | null;
  cwd: string;
  status: "idle" | "thinking" | "executing";
  sessionStartTime: number | null;

  // Thinking
  thinkingPhase: "connecting" | "loading_context" | "reasoning" | "generating" | null;
  thinkingDetail: string;

  // Events
  feedEntries: FeedEntry[];
  timelineEvents: TimelineEvent[];
  agents: AgentInfo[];
  streamedText: string;
  filterAgentId: string | null;

  // Stats
  toolCounts: Record<string, number>;
  opsPerMin: number[];
  filesTouched: string[];
  activeAgents: number;
  totalCost: number;

  // Actions
  init: () => void;
  sendPrompt: (text: string) => void;
  cancelQuery: () => void;
  setFilterAgent: (id: string | null) => void;
  handleMessage: (msg: ServerMessage) => void;
};

let idCounter = 0;
function nextId() {
  return `evt_${++idCounter}`;
}

export const useStore = create<DashboardState>((set, get) => ({
  connected: false,
  wsClient: null,
  sessionId: null,
  cwd: "",
  status: "idle",
  sessionStartTime: null,
  thinkingPhase: null,
  thinkingDetail: "",
  feedEntries: [],
  timelineEvents: [],
  agents: [],
  streamedText: "",
  filterAgentId: null,
  toolCounts: {},
  opsPerMin: [],
  filesTouched: [],
  activeAgents: 0,
  totalCost: 0,

  init: () => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    // In production, WS is on same host:port as the page
    // In dev (Vite), proxy handles ws:// or connect to 3001 directly
    const wsHost = window.location.host.includes("5173")
      ? `${window.location.hostname}:3001`
      : window.location.host;
    const url = `${protocol}://${wsHost}`;

    const client = new WsClient(
      url,
      (msg) => get().handleMessage(msg),
      (connected) => set({ connected })
    );
    client.connect();
    set({ wsClient: client });
  },

  sendPrompt: (text: string) => {
    const { wsClient } = get();
    if (!wsClient) return;
    // Clear previous session data
    set({
      feedEntries: [],
      timelineEvents: [],
      agents: [],
      streamedText: "",
      filterAgentId: null,
      thinkingPhase: null,
      thinkingDetail: "",
    });
    wsClient.send({ type: "prompt", text });
  },

  cancelQuery: () => {
    get().wsClient?.send({ type: "cancel" });
  },

  setFilterAgent: (id: string | null) => {
    set({ filterAgentId: id });
  },

  handleMessage: (msg: ServerMessage) => {
    switch (msg.type) {
      case "session_start":
        set({
          sessionId: msg.sessionId,
          cwd: msg.cwd,
          sessionStartTime: msg.startTime,
        });
        break;

      case "status":
        set({
          status: msg.state,
          // Clear thinking when idle
          ...(msg.state === "idle" ? { thinkingPhase: null, thinkingDetail: "" } : {}),
        });
        break;

      case "thinking":
        set({ thinkingPhase: msg.phase, thinkingDetail: msg.detail || "" });
        break;

      case "text_delta":
        set((s) => ({ streamedText: s.streamedText + msg.text }));
        break;

      case "tool_start":
        set((s) => ({
          timelineEvents: [
            ...s.timelineEvents,
            {
              id: msg.id,
              type: "tool",
              tool: msg.tool,
              label: msg.tool,
              timestamp: Date.now(),
              agentId: msg.agentId,
              status: "active",
            },
          ],
          feedEntries: [
            ...s.feedEntries,
            {
              id: nextId(),
              timestamp: Date.now(),
              icon: msg.tool,
              tool: msg.tool,
              text: `${msg.tool} started`,
              agentId: msg.agentId,
            },
          ],
        }));
        break;

      case "tool_input_delta": {
        // Update the timeline event label with partial tool input info
        set((s) => {
          const events = [...s.timelineEvents];
          const idx = events.findIndex((e) => e.id === msg.id);
          if (idx >= 0) {
            const ev = { ...events[idx] };
            // Try to extract a useful label from the partial JSON
            const pathMatch = msg.partialJson.match(/"(?:file_path|pattern|command|query|url)"\s*:\s*"([^"]*)/);
            if (pathMatch) {
              const val = pathMatch[1];
              const short = val.length > 40 ? "..." + val.slice(-37) : val;
              ev.label = `${ev.tool}: ${short}`;
            }
            events[idx] = ev;
          }
          return { timelineEvents: events };
        });
        break;
      }

      case "tool_end":
        set((s) => {
          const events = s.timelineEvents.map((e) =>
            e.id === msg.id
              ? { ...e, status: "completed" as const, duration: msg.duration }
              : e
          );
          return {
            timelineEvents: events,
            feedEntries: [
              ...s.feedEntries,
              {
                id: nextId(),
                timestamp: Date.now(),
                icon: msg.tool,
                tool: msg.tool,
                text: `${msg.tool} completed (${msg.duration}ms)`,
                agentId: msg.agentId,
              },
            ],
          };
        });
        break;

      case "agent_spawn":
        set((s) => {
          // Update existing or add new
          const existing = s.agents.findIndex((a) => a.id === msg.id);
          const updated = [...s.agents];
          if (existing >= 0) {
            updated[existing] = {
              ...updated[existing],
              description: msg.description,
              type: msg.agentType,
            };
          } else {
            updated.push({
              id: msg.id,
              type: msg.agentType,
              description: msg.description,
              status: "active",
              spawnTime: Date.now(),
            });
          }
          return {
            agents: updated,
            feedEntries: [
              ...s.feedEntries,
              {
                id: nextId(),
                timestamp: Date.now(),
                icon: "Task",
                tool: "Task",
                text: `Agent spawned: ${msg.description}`,
                agentId: msg.id,
              },
            ],
          };
        });
        break;

      case "agent_complete":
        set((s) => ({
          agents: s.agents.map((a) =>
            a.id === msg.id
              ? { ...a, status: "completed" as const, endTime: Date.now() }
              : a
          ),
          feedEntries: [
            ...s.feedEntries,
            {
              id: nextId(),
              timestamp: Date.now(),
              icon: "Task",
              tool: "Task",
              text: `Agent completed (${(msg.duration / 1000).toFixed(1)}s)`,
              agentId: msg.id,
            },
          ],
        }));
        break;

      case "stats_update":
        set({
          toolCounts: msg.toolCounts,
          opsPerMin: msg.opsPerMin,
          filesTouched: msg.filesTouched,
          activeAgents: msg.activeAgents,
          totalCost: msg.totalCost ?? 0,
        });
        break;

      case "result":
        set((s) => ({
          feedEntries: [
            ...s.feedEntries,
            {
              id: nextId(),
              timestamp: Date.now(),
              icon: "result",
              text: "Query completed",
            },
          ],
        }));
        break;

      case "error":
        set((s) => ({
          feedEntries: [
            ...s.feedEntries,
            {
              id: nextId(),
              timestamp: Date.now(),
              icon: "error",
              text: msg.message,
            },
          ],
        }));
        break;
    }
  },
}));
