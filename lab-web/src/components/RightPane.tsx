import { WormCanvas } from "./WormCanvas";
import { SimulationTransportHud } from "./SimulationTransportHud";
import { StatusHud } from "./StatusHud";

export function RightPane() {
  return (
    <div className="relative flex h-full w-full flex-col bg-black">
      <div className="min-h-0 flex-1">
        <WormCanvas />
      </div>
      <StatusHud />
      <SimulationTransportHud />
    </div>
  );
}
