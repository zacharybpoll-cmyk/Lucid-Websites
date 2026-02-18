import { spawn, type ChildProcess } from "child_process";
import type { ServerMessage } from "../../shared/src/types.js";
import { EventProcessor } from "./event-processor.js";
import { StatsTracker } from "./stats-tracker.js";

export class SessionManager {
  private childProcess: ChildProcess | null = null;
  private sessionId: string | null = null;
  private cwd: string;
  private stats: StatsTracker;
  private emit: (msg: ServerMessage) => void;

  constructor(cwd: string, emit: (msg: ServerMessage) => void) {
    this.cwd = cwd;
    this.emit = emit;
    this.stats = new StatsTracker();
  }

  async runQuery(prompt: string) {
    const startTime = Date.now();
    const processor = new EventProcessor(this.emit, this.stats);

    this.emit({ type: "status", state: "thinking" });
    this.emit({ type: "thinking", phase: "connecting", detail: "Launching Claude..." });
    this.stats.reset();
    this.stats.start((statsMsg) => this.emit(statsMsg));

    try {
      // Spawn claude CLI as subprocess with stream-json output
      const args = [
        "-p",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--model", "sonnet",
        "--permission-mode", "bypassPermissions",
        "--max-budget-usd", "5",
        prompt,
      ];

      // Remove CLAUDECODE env var so claude doesn't refuse to run
      const env = { ...process.env };
      delete env.CLAUDECODE;

      // Build command string for shell execution — required because
      // claude is a Node.js script that needs shell PATH resolution
      const escapedArgs = args.map((a) =>
        a.includes(" ") ? `'${a.replace(/'/g, "'\\''")}'` : a
      );
      const cmd = `claude ${escapedArgs.join(" ")}`;

      this.childProcess = spawn(cmd, [], {
        cwd: this.cwd,
        env,
        stdio: ["ignore", "pipe", "pipe"],
        shell: true,
      });

      let buffer = "";
      let resultText = "";

      this.childProcess.stdout?.on("data", (chunk: Buffer) => {
        buffer += chunk.toString();

        // Process complete JSON lines
        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // Keep incomplete line in buffer

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          try {
            const message = JSON.parse(trimmed);
            this.handleMessage(message, processor, startTime);

            // Capture result text
            if (message.type === "result") {
              if (message.subtype === "success") {
                resultText = message.result || "";
                if (message.total_cost_usd) {
                  this.stats.setCost(message.total_cost_usd);
                }
              } else {
                const errors = message.errors;
                resultText = `Error: ${errors?.join(", ") || "Unknown error"}`;
              }
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      });

      this.childProcess.stderr?.on("data", (chunk: Buffer) => {
        const text = chunk.toString().trim();
        if (text) {
          console.error("[claude stderr]", text);
        }
      });

      // Wait for process to complete
      await new Promise<void>((resolve, reject) => {
        this.childProcess!.on("close", (code) => {
          // Process any remaining buffer
          if (buffer.trim()) {
            try {
              const message = JSON.parse(buffer.trim());
              this.handleMessage(message, processor, startTime);
              if (message.type === "result") {
                if (message.subtype === "success") {
                  resultText = message.result || "";
                  if (message.total_cost_usd) {
                    this.stats.setCost(message.total_cost_usd);
                  }
                }
              }
            } catch {
              // ignore
            }
          }
          if (code !== 0 && code !== null) {
            reject(new Error(`claude exited with code ${code}`));
          } else {
            resolve();
          }
        });

        this.childProcess!.on("error", reject);
      });

      this.emit({
        type: "result",
        text: resultText,
        sessionId: this.sessionId || "",
        costUsd: this.stats.snapshot().totalCost,
        durationMs: Date.now() - startTime,
      });
    } catch (err: any) {
      if (err.message?.includes("cancelled") || err.killed) {
        this.emit({ type: "error", message: "Query cancelled" });
      } else {
        this.emit({
          type: "error",
          message: err.message || "Unknown error",
        });
      }
    } finally {
      this.stats.stop();
      processor.reset();
      this.childProcess = null;
      this.emit({ type: "status", state: "idle" });
    }
  }

  private handleMessage(
    message: any,
    processor: EventProcessor,
    startTime: number
  ) {
    switch (message.type) {
      case "system":
        if (message.subtype === "init") {
          this.sessionId = message.session_id;
          this.emit({
            type: "session_start",
            sessionId: message.session_id,
            cwd: message.cwd || this.cwd,
            startTime,
          });
          this.emit({ type: "status", state: "executing" });
          this.emit({ type: "thinking", phase: "loading_context", detail: "Loading context & tools..." });
        }
        break;

      case "stream_event": {
        const event = message.event;
        if (event) {
          processor.processStreamEvent(event, message.parent_tool_use_id);
        }
        break;
      }

      case "assistant":
        // Full assistant message — can extract tool use info
        if (message.message?.content) {
          for (const block of message.message.content) {
            if (block.type === "tool_use") {
              this.stats.recordToolUse(block.name);
            }
          }
        }
        break;
    }
  }

  cancel() {
    if (this.childProcess) {
      this.childProcess.kill("SIGTERM");
    }
  }

  setCwd(path: string) {
    this.cwd = path;
  }

  getCwd() {
    return this.cwd;
  }

  getSessionId() {
    return this.sessionId;
  }
}
