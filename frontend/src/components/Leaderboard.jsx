import { useState, useEffect, useRef } from "react";
import TireBadge from "./TireBadge";
import { getTeamColor } from "../lib/constants";

function GapDisplay({ gap, retired, lapsDown }) {
  if (retired) return <span className="text-ink-500 font-bold text-xs">DNF</span>;
  // A car a lap or more behind isn't meaningfully comparable by time (that's
  // why the backend sends a sentinel instead of a real number here) — show
  // it the way a real F1 timing screen does, as laps rather than seconds.
  if (lapsDown > 0) return <span className="mono text-ink-300 text-xs">+{lapsDown} LAP{lapsDown > 1 ? "S" : ""}</span>;
  if (gap === Infinity || gap > 9999) return <span className="text-ink-500 font-bold text-xs">DNF</span>;
  if (gap === 0) return <span className="text-f1red font-extrabold text-xs tracking-widest">LEADER</span>;
  return <span className="mono text-ink-50 text-xs">+{gap.toFixed(3)}</span>;
}

const PODIUM = ["bg-f1red text-white", "bg-slate-300 text-black", "bg-amber-600 text-white"];

export default function Leaderboard({ cars = [], lap, totalLaps }) {
  const prevPositions = useRef({});
  const [fastestLapCarId, setFastestLapCarId] = useState(null);

  useEffect(() => {
    let bestTime = Infinity;
    let bestId = null;
    cars.forEach(c => {
      if (c.lap_time_s && c.lap_time_s < bestTime) {
        bestTime = c.lap_time_s;
        bestId = c.car_id;
      }
    });
    setFastestLapCarId(bestId);
    return () => {
      const newPrev = {};
      cars.forEach(c => { newPrev[c.car_id] = c.position; });
      prevPositions.current = newPrev;
    };
  }, [cars]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <h2>Leaderboard</h2>
        {lap != null && (
          <span className="chip mono">
            Lap <span className="text-white font-bold">{lap}</span>/{totalLaps}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-1 pr-0.5">
        {cars.length === 0 && (
          <div className="space-y-1.5 mt-2">
            {Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton h-9" />)}
          </div>
        )}
        {cars.map((car, idx) => {
          const prevPos = prevPositions.current[car.car_id];
          const posChange = prevPos != null ? prevPos - car.position : 0;
          const teamColor = getTeamColor(car.team);
          const isFastest = car.car_id === fastestLapCarId;

          return (
            <div
              key={car.car_id}
              className={`group flex items-center gap-2 pl-0 pr-2.5 py-1 rounded-lg text-sm transition-colors overflow-hidden
                ${car.retired ? "opacity-45" : car.laps_down > 0 ? "opacity-80" : ""}
                ${idx === 0 && !car.retired
                  ? "bg-gradient-to-r from-f1red/20 to-white/[.03] ring-1 ring-f1red/40"
                  : "bg-white/[.03] hover:bg-white/[.07]"}`}
            >
              {/* Team colour stripe */}
              <span className="self-stretch w-1 flex-shrink-0" style={{ background: teamColor }} />

              {/* Position */}
              <span className={`w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 text-xs font-extrabold mono ${
                car.retired ? "bg-white/5 text-ink-500" : idx < 3 ? PODIUM[idx] : "bg-white/[.06] text-ink-300"
              }`}>
                {car.position}
              </span>

              {/* Position change arrow */}
              <span className="w-3 text-center flex-shrink-0">
                {posChange > 0
                  ? <span className="text-emerald-400 text-[9px]">▲</span>
                  : posChange < 0
                  ? <span className="text-red-400 text-[9px]">▼</span>
                  : null}
              </span>

              {/* Driver */}
              <span className="w-9 display font-extrabold text-white text-[17px] tracking-wider flex-shrink-0 leading-none">
                {car.driver_code}
              </span>

              {/* Tyre */}
              <TireBadge compound={car.tire_compound} age={car.tire_age_laps} />

              {/* Fastest lap */}
              {isFastest && (
                <span className="text-[9px] font-extrabold text-purple-300 bg-purple-500/20 border border-purple-400/30 px-1 rounded flex-shrink-0">FL</span>
              )}

              {/* DRS */}
              {car.drs && (
                <span className="text-[9px] font-extrabold text-cyan-300 bg-cyan-500/15 border border-cyan-400/30 px-1 rounded flex-shrink-0">DRS</span>
              )}

              {/* Gap */}
              <div className="flex-1 text-right">
                <GapDisplay gap={car.gap_to_leader_s} retired={car.retired} lapsDown={car.laps_down} />
              </div>

              {/* Pit indicator */}
              {car.is_in_pit && !car.retired && (
                <span className="text-[9px] font-bold bg-sky-600 text-white px-1.5 py-0.5 rounded flex-shrink-0 animate-pulse">PIT</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
