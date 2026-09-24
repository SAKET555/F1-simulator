import { useState, useEffect, useRef } from "react";
import TireBadge from "./TireBadge";
import { getTeamColor } from "../lib/constants";

function GapDisplay({ gap, retired }) {
  if (retired || gap === Infinity || gap > 9999) return <span className="text-gray-600 font-bold text-xs">DNF</span>;
  if (gap === 0) return <span className="text-f1red font-bold text-xs">LEAD</span>;
  return <span className="text-gray-300 text-xs">+{gap.toFixed(3)}s</span>;
}

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
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest">
          Leaderboard
        </h2>
        {lap != null && (
          <span className="text-xs text-gray-500">
            Lap <span className="text-white font-bold">{lap}</span>/{totalLaps}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-1 pr-0.5">
        {cars.length === 0 && (
          <p className="text-gray-600 text-sm text-center mt-8">Waiting for race data…</p>
        )}
        {cars.map((car, idx) => {
          const prevPos = prevPositions.current[car.car_id];
          const posChange = prevPos != null ? prevPos - car.position : 0;
          const teamColor = getTeamColor(car.team);
          const isFastest = car.car_id === fastestLapCarId;

          return (
            <div
              key={car.car_id}
              className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-sm transition-colors
                ${car.retired ? "opacity-50" : idx === 0 ? "bg-panel border border-f1red/30" : "bg-panel/60 hover:bg-panel"}`}
              style={{ borderLeft: `3px solid ${teamColor}` }}
            >
              {/* Position */}
              <span className={`w-5 text-center font-bold text-xs flex-shrink-0 ${
                car.retired ? "text-gray-600" : idx === 0 ? "text-f1red" : idx < 3 ? "text-yellow-400" : "text-gray-400"
              }`}>
                {car.position}
              </span>

              {/* Position change arrow */}
              <span className="w-3 text-center flex-shrink-0">
                {posChange > 0
                  ? <span className="text-green-400 text-[9px]">▲</span>
                  : posChange < 0
                  ? <span className="text-red-400 text-[9px]">▼</span>
                  : null}
              </span>

              {/* Driver */}
              <span className="w-8 font-mono font-bold text-white text-xs tracking-wider flex-shrink-0">
                {car.driver_code}
              </span>

              {/* Team color dot */}
              <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                style={{ background: teamColor }} />

              {/* Tyre */}
              <TireBadge compound={car.tire_compound} age={car.tire_age_laps} />

              {/* Fastest lap */}
              {isFastest && (
                <span className="text-[9px] font-bold text-purple-400 flex-shrink-0">FL</span>
              )}

              {/* DRS */}
              {car.drs && (
                <span className="text-[9px] font-bold text-cyan-400 flex-shrink-0">DRS</span>
              )}

              {/* Gap */}
              <div className="flex-1 text-right">
                <GapDisplay gap={car.gap_to_leader_s} retired={car.retired} />
              </div>

              {/* Pit indicator */}
              {car.is_in_pit && !car.retired && (
                <span className="text-[9px] bg-blue-700 text-white px-1 rounded flex-shrink-0">PIT</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
