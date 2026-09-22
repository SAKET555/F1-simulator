import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

const COMPOUND_HEX = {
  SOFT: "#dc2626",
  MEDIUM: "#ca8a04",
  HARD: "#d1d5db",
  INTERMEDIATE: "#16a34a",
  WET: "#2563eb",
  UNKNOWN: "#4b5563",
};

export default function StintAnalysis({ raceId, totalLaps = 70 }) {
  const [stints, setStints] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!raceId) return;
    setLoading(true);
    fetch(`${API_BASE}/races/${raceId}/stints`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => { setStints(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [raceId]);

  if (loading) return <div className="text-gray-600 text-xs p-4">Loading stints…</div>;

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Tyre Strategy</h3>

      {stints.length === 0 ? (
        <p className="text-gray-600 text-xs">No stint data available</p>
      ) : (
        <div className="space-y-1 overflow-auto max-h-80">
          {stints.map(driver => (
            <div key={driver.driver_code} className="flex items-center gap-2">
              <span className="w-8 text-xs font-bold text-gray-300 text-right flex-shrink-0">
                {driver.driver_code}
              </span>
              <div className="flex-1 h-5 flex rounded overflow-hidden bg-border/30">
                {driver.stints.map((stint, i) => {
                  const width = ((stint.end_lap - stint.start_lap + 1) / totalLaps) * 100;
                  const color = COMPOUND_HEX[stint.compound] || "#4b5563";
                  return (
                    <div
                      key={i}
                      title={`${stint.compound} Lap ${stint.start_lap}–${stint.end_lap} (${stint.laps} laps)`}
                      style={{ width: `${width}%`, background: color }}
                      className="border-r border-pitwall/50 flex items-center justify-center flex-shrink-0"
                    >
                      {stint.laps > 4 && (
                        <span className="text-[8px] font-bold text-black/70">
                          {stint.compound.charAt(0)}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}

          <div className="flex gap-3 mt-2 flex-wrap">
            {Object.entries(COMPOUND_HEX).filter(([k]) => k !== "UNKNOWN").map(([c, hex]) => (
              <div key={c} className="flex items-center gap-1">
                <div className="w-3 h-3 rounded-sm flex-shrink-0" style={{ background: hex }} />
                <span className="text-[10px] text-gray-500">{c.charAt(0) + c.slice(1).toLowerCase()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
