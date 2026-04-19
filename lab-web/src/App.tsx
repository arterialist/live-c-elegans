import { Allotment } from "allotment";
import { ControlsPane } from "./components/ControlsPane";
import { RightPane } from "./components/RightPane";
import { useLabWebSocket } from "./state/ws";
import { useGlobalShortcuts } from "./state/shortcuts";

export default function App() {
  useLabWebSocket();
  useGlobalShortcuts();
  return (
    <div className="h-full w-full bg-zinc-950 text-zinc-100 select-none">
      <Allotment defaultSizes={[66, 34]} minSize={300}>
        <Allotment.Pane minSize={320} snap={false}>
          <ControlsPane />
        </Allotment.Pane>
        <Allotment.Pane minSize={320} snap={false}>
          <RightPane />
        </Allotment.Pane>
      </Allotment>
    </div>
  );
}
