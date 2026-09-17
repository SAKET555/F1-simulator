import { Play, Pause } from "lucide-react";
import { SPEED_OPTIONS } from "../lib/constants";

export default function SpeedControl({
  speed, onSpeedChange,
  paused, onPause, onResume,
  status,
}) {
  const isLive = status === "live";
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Status pill */}
      <span
        className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
          status === "live"       ? "bg-green-600/20 text-green-400 animate-pulse" :
          status === "finished"   ? "bg-blue-600/20  text-blue-400"  :
          status === "connecting" ? "bg-yellow-600/20 text-yellow-400" :
          status === "error"      ? "bg-red-600/20   text-red-400"   :
          "bg-gray-600/20 text-gray-400"
        }`}
      >
        {status.toUpperCase()}
      </span>

      {/* Play / Pause */}
      <button
        onClick={paused ? onResume : onPause}
        disabled={!isLive}
        className="p-1.5 rounded bg-panel border border-border hover:border-gray-500 disabled:opacity-30 transition-colors"
        title={paused ? "Resume" : "Pause"}
      >
        {paused ? <Play size={14} className="text-green-400" /> : <Pause size={14} className="text-yellow-400" />}
      </button>

      {/* Speed toggles */}
      <div className="flex gap-1">
        {SPEED_OPTIONS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => onSpeedChange(value)}
            className={`px-2.5 py-1 rounded text-xs font-bold transition-colors ${
              speed === value
                ? "bg-f1red text-white"
                : "bg-panel border border-border text-gray-400 hover:text-white hover:border-gray-500"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
