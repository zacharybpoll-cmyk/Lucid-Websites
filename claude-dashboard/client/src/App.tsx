import { useEffect } from "react";
import { useStore } from "./store";
import { LeftPanel } from "./components/LeftPanel";
import { CenterPanel } from "./components/CenterPanel";
import { RightPanel } from "./components/RightPanel";

export function App() {
  const init = useStore((s) => s.init);

  useEffect(() => {
    init();
  }, [init]);

  return (
    <div className="dashboard">
      <LeftPanel />
      <CenterPanel />
      <RightPanel />
    </div>
  );
}
