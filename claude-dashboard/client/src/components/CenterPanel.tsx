import { useStore } from "../store";
import { Timeline } from "./Timeline";
import { ActivityFeed } from "./ActivityFeed";
import { PromptInput } from "./PromptInput";
import { ThinkingVisualizer } from "./ThinkingVisualizer";

export function CenterPanel() {
  const thinkingPhase = useStore((s) => s.thinkingPhase);
  const feedEntries = useStore((s) => s.feedEntries);
  const status = useStore((s) => s.status);

  // Show thinking visualizer when thinking and no feed entries yet
  const showThinking =
    status !== "idle" && thinkingPhase !== null && feedEntries.length === 0;

  return (
    <div className="panel center-panel">
      <div className="center-top">
        <Timeline />
      </div>
      <div className="center-middle">
        {showThinking ? <ThinkingVisualizer /> : <ActivityFeed />}
      </div>
      <div className="center-bottom">
        <PromptInput />
      </div>
    </div>
  );
}
