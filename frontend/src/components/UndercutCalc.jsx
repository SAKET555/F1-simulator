import { useState } from "react";
import { API_BASE } from "../lib/constants";

const COMPOUNDS = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"];

export default function UndercutCalc({ raceId, cars = [], currentLap = 1, totalLaps = 70 }) {
  const [carId, setCarId] = useState("");
  const [targetCarId, setTargetCarId] = useState("");
  const [pitLap, setPitLap] = useState(currentLap + 3);
  const [compound, setCompound] = useState("MEDIUM");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  async function calculate() {
    if (!carId || !targetCarId || !raceId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/simulate/undercut`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          race_id: raceId,
          car_id: parseInt(carId),
          target_car_id: parseInt(targetCarId),
          current_lap: currentLap,
          pit_lap: parseInt(pitLap),
          target_compound: compound,
        }),
      });
      if (res.ok) setResult(await res.json());
    } catch {}
    setLoading(false);
  }

  const activeCars = cars.filter(c => c.gap_to_leader_s < 200);

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Undercut Calc</h3>

      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-gray-500 block mb-0.5">Your Car</label>
            <select className="w-full bg-pitwall border border-border rounded px-2 py-1 text-xs text-white"
              value={carId} onChange={e => setCarId(e.target.value)}>
              <option value="">Pick driver</option>
              {activeCars.map(c => <option key={c.car_id} value={c.car_id}>{c.driver_code}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-0.5">Target Car</label>
            <select className="w-full bg-pitwall border border-border rounded px-2 py-1 text-xs text-white"
              value={targetCarId} onChange={e => setTargetCarId(e.target.value)}>
              <option value="">Pick driver</option>
              {activeCars.map(c => <option key={c.car_id} value={c.car_id}>{c.driver_code}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-gray-500 block mb-0.5">Pit Lap</label>
            <input type="number" min={currentLap + 1} max={totalLaps - 5}
              value={pitLap} onChange={e => setPitLap(parseInt(e.target.value))}
              className="w-full bg-pitwall border border-border rounded px-2 py-1 text-xs text-white" />
          </div>
          <div>
            <label className="text-[10px] text-gray-500 block mb-0.5">Compound</label>
            <select className="w-full bg-pitwall border border-border rounded px-2 py-1 text-xs text-white"
              value={compound} onChange={e => setCompound(e.target.value)}>
              {COMPOUNDS.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>
        </div>

        <button onClick={calculate} disabled={loading || !carId || !targetCarId}
          className="w-full py-1.5 bg-f1red text-white text-xs font-bold rounded hover:bg-red-700 disabled:opacity-50 transition">
          {loading ? "Calculating…" : "Analyse Undercut"}
        </button>
      </div>

      {result && (
        <div className={`mt-3 p-3 rounded-lg border text-xs ${
          result.will_undercut ? "bg-green-900/20 border-green-700/30" : "bg-orange-900/20 border-orange-700/30"
        }`}>
          <div className={`font-bold mb-1 ${result.will_undercut ? "text-green-400" : "text-orange-400"}`}>
            {result.will_undercut ? "✓ Undercut Works" : "⚠ Overcut Recommended"}
          </div>
          <div className="space-y-0.5 text-gray-300">
            <div>Gap before pit: <span className="text-white font-mono">
              {result.gap_before_s > 0 ? "+" : ""}{result.gap_before_s.toFixed(2)}s
            </span></div>
            <div>Projected after: <span className={`font-mono font-bold ${result.projected_gap_after_s < 0 ? "text-green-400" : "text-red-400"}`}>
              {result.projected_gap_after_s > 0 ? "+" : ""}{result.projected_gap_after_s.toFixed(2)}s
            </span></div>
            {result.breakeven_lap && <div>Overtake ~Lap {result.breakeven_lap}</div>}
            <p className="text-gray-400 mt-2 leading-relaxed">{result.recommendation}</p>
          </div>
        </div>
      )}
    </div>
  );
}
