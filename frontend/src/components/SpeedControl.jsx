import { Play, Pause } from "lucide-react";
import { SPEED_OPTIONS } from "../lib/constants";

const PILL = {
  live:       "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  finished:   "bg-sky-500/15 text-sky-300 border-sky-500/30",
  connecting: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  error:      "bg-red-500/15 text-red-300 border-red-500/30",
};

export default function SpeedControl({
  speed, onSpeedChange,
  paused, onPause, onResume,
  status,
}) {
  const isLive = status === "live";
  return (
    <div className="flex items-center gap-2">
      {/* Status pill */}
      <span
        className={`hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold tracking-widest border ${
          PILL[status] ?? "bg-white/5 text-ink-300 border-white/10"
        }`}
      >
        {isLive && !paused && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />}
        {status === "live" ? (paused ? "PAUSED" : "REPLAYING") : status.toUpperCase()}
      </span>

      {/* Play / Pause */}
      <button
        onClick={paused ? onResume : onPause}
        disabled={!isLive}
        className="h-8 w-8 inline-flex items-center justify-center rounded-lg bg-white/[.04] border border-white/10 hover:border-white/30 disabled:opacity-30 transition-colors"
        title={paused ? "Resume (Space)" : "Pause (Space)"}
      >
        {paused ? <Play size={14} className="text-emerald-400" /> : <Pause size={14} className="text-amber-300" />}
      </button>

      {/* Speed segmented control */}
      <div className="inline-flex p-0.5 rounded-lg bg-white/[.04] border border-white/10">
        {SPEED_OPTIONS.map(({ label, value }) => (
          <button
            key={value}
            onClick={() => onSpeedChange(value)}
            className={`px-2.5 h-7 rounded-md text-xs font-bold mono transition-all ${
              speed === value
                ? "bg-f1red text-white shadow-[0_0_12px_rgba(225,6,0,.55)]"
                : "text-ink-300 hover:text-white"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
