// ── Client → Server messages ──

export type ClientMessage =
  | { type: "prompt"; text: string; workingDirectory?: string }
  | { type: "cancel" }
  | { type: "set_cwd"; path: string };

// ── Server → Client messages ──

export type ServerMessage =
  | SessionStartMessage
  | TextDeltaMessage
  | ToolStartMessage
  | ToolInputDeltaMessage
  | ToolEndMessage
  | AgentSpawnMessage
  | AgentCompleteMessage
  | StatsUpdateMessage
  | ResultMessage
  | ErrorMessage
  | StatusMessage
  | ThinkingMessage;

export type ThinkingMessage = {
  type: "thinking";
  phase: "connecting" | "loading_context" | "reasoning" | "generating";
  detail?: string;
};

export type SessionStartMessage = {
  type: "session_start";
  sessionId: string;
  cwd: string;
  startTime: number;
};

export type TextDeltaMessage = {
  type: "text_delta";
  text: string;
  agentId?: string;
};

export type ToolStartMessage = {
  type: "tool_start";
  id: string;
  tool: string;
  input?: string;
  agentId?: string;
};

export type ToolInputDeltaMessage = {
  type: "tool_input_delta";
  id: string;
  partialJson: string;
};

export type ToolEndMessage = {
  type: "tool_end";
  id: string;
  tool: string;
  duration: number;
  agentId?: string;
};

export type AgentSpawnMessage = {
  type: "agent_spawn";
  id: string;
  agentType: string;
  description: string;
};

export type AgentCompleteMessage = {
  type: "agent_complete";
  id: string;
  duration: number;
};

export type StatsUpdateMessage = {
  type: "stats_update";
  toolCounts: Record<string, number>;
  opsPerMin: number[];
  filesTouched: string[];
  activeAgents: number;
  totalCost?: number;
};

export type ResultMessage = {
  type: "result";
  text: string;
  sessionId: string;
  costUsd?: number;
  durationMs?: number;
};

export type ErrorMessage = {
  type: "error";
  message: string;
};

export type StatusMessage = {
  type: "status";
  state: "idle" | "thinking" | "executing";
};

// ── Shared domain types ──

export type AgentInfo = {
  id: string;
  type: string;
  description: string;
  status: "active" | "completed";
  spawnTime: number;
  endTime?: number;
};

export type TimelineEvent = {
  id: string;
  type: "tool" | "text" | "agent_spawn" | "agent_complete";
  tool?: string;
  label: string;
  timestamp: number;
  duration?: number;
  agentId?: string;
  status: "active" | "completed";
};

export type FeedEntry = {
  id: string;
  timestamp: number;
  icon: string;
  tool?: string;
  text: string;
  agentId?: string;
};

export const TOOL_COLORS: Record<string, string> = {
  Read: "blue",
  Grep: "blue",
  Glob: "blue",
  Edit: "green",
  Write: "green",
  NotebookEdit: "green",
  Bash: "orange",
  Task: "purple",
  WebFetch: "cyan",
  WebSearch: "cyan",
};
