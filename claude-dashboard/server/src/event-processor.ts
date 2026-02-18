import type { ServerMessage } from "../../shared/src/types.js";
import { StatsTracker } from "./stats-tracker.js";

type BlockState = {
  index: number;
  type: "text" | "tool_use";
  toolName?: string;
  toolId?: string;
  inputJson: string;
  startTime: number;
  agentId?: string;
};

type RawStreamEvent = {
  type: string;
  index?: number;
  content_block?: {
    type: string;
    name?: string;
    id?: string;
    text?: string;
  };
  delta?: {
    type: string;
    text?: string;
    partial_json?: string;
  };
};

export class EventProcessor {
  private blocks = new Map<number, BlockState>();
  private textBuffer = "";
  private textFlushTimer: ReturnType<typeof setTimeout> | null = null;
  private emit: (msg: ServerMessage) => void;
  private stats: StatsTracker;
  private activeAgents = new Map<string, { spawnTime: number }>();
  private hasEmittedFirstContent = false;

  constructor(emit: (msg: ServerMessage) => void, stats: StatsTracker) {
    this.emit = emit;
    this.stats = stats;
  }

  reset() {
    this.blocks.clear();
    this.textBuffer = "";
    if (this.textFlushTimer) {
      clearTimeout(this.textFlushTimer);
      this.textFlushTimer = null;
    }
    this.activeAgents.clear();
    this.hasEmittedFirstContent = false;
  }

  processStreamEvent(event: RawStreamEvent, parentToolUseId: string | null) {
    const agentId = parentToolUseId ?? undefined;

    switch (event.type) {
      case "message_start": {
        // Model is now processing — transition from "connecting" to "reasoning"
        this.emit({ type: "thinking", phase: "reasoning", detail: "Analyzing prompt..." });
        break;
      }

      case "content_block_start": {
        const idx = event.index ?? 0;
        const block = event.content_block;
        if (!block) break;

        if (block.type === "tool_use") {
          if (!this.hasEmittedFirstContent) {
            this.hasEmittedFirstContent = true;
            this.emit({ type: "thinking", phase: "generating", detail: "Deciding on tools..." });
          }
          const toolName = block.name || "unknown";
          const toolId = block.id || `tool_${idx}_${Date.now()}`;
          this.blocks.set(idx, {
            index: idx,
            type: "tool_use",
            toolName,
            toolId,
            inputJson: "",
            startTime: Date.now(),
            agentId,
          });

          // Check if this is a Task (sub-agent spawn)
          if (toolName === "Task") {
            this.emit({
              type: "agent_spawn",
              id: toolId,
              agentType: "sub-agent",
              description: "Sub-agent spawned",
            });
            this.activeAgents.set(toolId, { spawnTime: Date.now() });
            this.stats.setActiveAgents(this.activeAgents.size);
          }

          this.emit({
            type: "tool_start",
            id: toolId,
            tool: toolName,
            agentId,
          });
          this.stats.recordToolUse(toolName);
        } else if (block.type === "text") {
          if (!this.hasEmittedFirstContent) {
            this.hasEmittedFirstContent = true;
            this.emit({ type: "thinking", phase: "generating", detail: "Composing response..." });
          }
          this.blocks.set(idx, {
            index: idx,
            type: "text",
            inputJson: "",
            startTime: Date.now(),
            agentId,
          });
        }
        break;
      }

      case "content_block_delta": {
        const idx = event.index ?? 0;
        const delta = event.delta;
        if (!delta) break;

        if (delta.type === "text_delta" && delta.text) {
          this.bufferText(delta.text, agentId);
        } else if (delta.type === "input_json_delta" && delta.partial_json !== undefined) {
          const block = this.blocks.get(idx);
          if (block && block.type === "tool_use") {
            block.inputJson += delta.partial_json;

            // Try to extract description for Task tool
            if (block.toolName === "Task" && block.toolId) {
              this.tryUpdateAgentDescription(block.toolId, block.inputJson);
            }

            // Extract file paths for stats
            this.tryExtractFilePath(block.inputJson);

            this.emit({
              type: "tool_input_delta",
              id: block.toolId!,
              partialJson: delta.partial_json,
            });
          }
        }
        break;
      }

      case "content_block_stop": {
        const idx = event.index ?? 0;
        const block = this.blocks.get(idx);
        if (!block) break;

        if (block.type === "text") {
          this.flushText(agentId);
        } else if (block.type === "tool_use" && block.toolId) {
          const duration = Date.now() - block.startTime;
          this.emit({
            type: "tool_end",
            id: block.toolId,
            tool: block.toolName!,
            duration,
            agentId,
          });

          // If Task tool completed, mark agent complete
          if (block.toolName === "Task" && this.activeAgents.has(block.toolId)) {
            const agent = this.activeAgents.get(block.toolId)!;
            this.activeAgents.delete(block.toolId);
            this.stats.setActiveAgents(this.activeAgents.size);
            this.emit({
              type: "agent_complete",
              id: block.toolId,
              duration: Date.now() - agent.spawnTime,
            });
          }
        }

        this.blocks.delete(idx);
        break;
      }
    }
  }

  private bufferText(text: string, agentId?: string) {
    this.textBuffer += text;
    if (!this.textFlushTimer) {
      this.textFlushTimer = setTimeout(() => this.flushText(agentId), 16);
    }
  }

  private flushText(agentId?: string) {
    if (this.textFlushTimer) {
      clearTimeout(this.textFlushTimer);
      this.textFlushTimer = null;
    }
    if (this.textBuffer) {
      this.emit({ type: "text_delta", text: this.textBuffer, agentId });
      this.textBuffer = "";
    }
  }

  private tryUpdateAgentDescription(toolId: string, json: string) {
    try {
      // Try to extract "description" or "prompt" from partial JSON
      const descMatch = json.match(/"description"\s*:\s*"([^"]+)"/);
      if (descMatch) {
        this.emit({
          type: "agent_spawn",
          id: toolId,
          agentType: "sub-agent",
          description: descMatch[1],
        });
      }
    } catch {
      // Partial JSON, ignore
    }
  }

  private tryExtractFilePath(json: string) {
    const pathMatch = json.match(/"(?:file_path|path|command)"\s*:\s*"([^"]+)"/);
    if (pathMatch) {
      this.stats.recordFileTouched(pathMatch[1]);
    }
  }
}
