import type { StatsUpdateMessage } from "../../shared/src/types.js";

export class StatsTracker {
  private toolCounts: Record<string, number> = {};
  private opsTimestamps: number[] = [];
  private opsPerMinHistory: number[] = [];
  private filesTouched = new Set<string>();
  private activeAgentCount = 0;
  private totalCost = 0;
  private intervalId: ReturnType<typeof setInterval> | null = null;

  start(onUpdate: (stats: StatsUpdateMessage) => void) {
    this.intervalId = setInterval(() => {
      this.computeOpsPerMin();
      onUpdate(this.snapshot());
    }, 1000);
  }

  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  reset() {
    this.toolCounts = {};
    this.opsTimestamps = [];
    this.opsPerMinHistory = [];
    this.filesTouched.clear();
    this.activeAgentCount = 0;
    this.totalCost = 0;
  }

  recordToolUse(tool: string) {
    this.toolCounts[tool] = (this.toolCounts[tool] || 0) + 1;
    this.opsTimestamps.push(Date.now());
  }

  recordFileTouched(path: string) {
    this.filesTouched.add(path);
  }

  setActiveAgents(count: number) {
    this.activeAgentCount = count;
  }

  setCost(cost: number) {
    this.totalCost = cost;
  }

  private computeOpsPerMin() {
    const now = Date.now();
    const oneMinAgo = now - 60_000;
    this.opsTimestamps = this.opsTimestamps.filter((t) => t > oneMinAgo);
    this.opsPerMinHistory.push(this.opsTimestamps.length);
    if (this.opsPerMinHistory.length > 60) {
      this.opsPerMinHistory = this.opsPerMinHistory.slice(-60);
    }
  }

  snapshot(): StatsUpdateMessage {
    return {
      type: "stats_update",
      toolCounts: { ...this.toolCounts },
      opsPerMin: [...this.opsPerMinHistory],
      filesTouched: [...this.filesTouched],
      activeAgents: this.activeAgentCount,
      totalCost: this.totalCost,
    };
  }
}
