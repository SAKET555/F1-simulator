import { useState, useEffect } from "react";
import { API_BASE } from "../lib/constants";

const COMPOUNDS = [
  { value: "SOFT",         label: "Soft",   cls: "bg-red-600 text-white"    },
  { value: "MEDIUM",       label: "Medium", cls: "bg-yellow-400 text-black" },
  { value: "HARD",         label: "Hard",   cls: "bg-gray-200 text-black"   },
  { value: "INTERMEDIATE", label: "Inter",  cls: "bg-green-600 text-white"  },
  { value: "WET",          label: "Wet",    cls: "bg-blue-600 text-white"   },
];

export default function CounterfactualPanel({ raceId, cars = [], totalLaps = 70, currentLap = 1 }) {
  const minPit = currentLap + 1;
  const maxPit = Math.max(totalLaps - 2, minPit + 1);

  const [carId,          setCarId]          = useState("");
  const [pitLap,         setPitLap]         = useState(minPit + 4);
  const [targetCompound, setTargetCompound] = useState("HARD");
  const [result,         setResult]         = useState(null);
  const [loading,        setLoading]        = useState(false);
  const [error,          setError]          = useState(null);

  // Keep pitLap valid as race progresses
  useEffect(() => {
    if (pitLap <= currentLap) {
      setPitLap(Math.min(currentLap + 5, maxPit));
    }
  }, [currentLap]);

  async function runSimulation() {
    if (!carId || !raceId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/simulate/counterfactual`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          race_id:         raceId,
          car_id:          Number(carId),
          pit_lap:         Number(pitLap),
          target_compound: targetCompound,
          current_lap:     currentLap,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail ?? "Request failed");
      }
      setResult(await resp.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const deltaWin    = result ? result.delta_win_pct    : null;
  const deltaPodium = result ? result.delta_podium_pct : null;

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest">
        Counterfactual — "What If?"
      </h2>

      {/* Driver picker */}
      <div>
        <label className="text-xs text-gray-500 block mb-1">Driver</label>
        <select
          className="w-full bg-pitwall border border-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-f1red"
          value={carId}
          onChange={(e) => { setCarId(e.target.value); setResult(null); }}
        >
          <option value="">— select driver —</option>
          {cars.map((c) => (
            <option key={c.car_id} value={c.car_id}>
              P{c.position} {c.driver_code} — {c.team}
            </option>
          ))}
        </select>
      </div>

      {/* Pit lap slider */}
      <div>
        <label className="text-xs text-gray-500 block mb-1">
          Pit on Lap{" "}
          <span className="text-white font-bold">{pitLap}</span>
          <span className="text-gray-600 ml-1">(currently lap {currentLap})</span>
        </label>
        <input
          type="range"
          min={minPit}
          max={maxPit}
          value={Math.min(Math.max(pitLap, minPit), maxPit)}
          onChange={(e) => setPitLap(Number(e.target.value))}
          className="w-full accent-f1red"
        />
        <div className="flex justify-between text-xs text-gray-600 mt-0.5">
          <span>Lap {minPit}</span>
          <span>Lap {maxPit}</span>
        </div>
      </div>

      {/* Target compound */}
      <div>
        <label className="text-xs text-gray-500 block mb-2">Target Compound</label>
        <div className="flex gap-1.5 flex-wrap">
          {COMPOUNDS.map(({ value, label, cls }) => (
            <button
              key={value}
              onClick={() => setTargetCompound(value)}
              className={`px-3 py-1 rounded text-xs font-bold transition-all ${cls} ${
                targetCompound === value
                  ? "ring-2 ring-white scale-105"
                  : "opacity-50 hover:opacity-80"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Run button */}
      <button
        onClick={runSimulation}
        disabled={!carId || loading || currentLap >= totalLaps - 1}
        className="w-full py-2 rounded bg-f1red hover:bg-red-700 disabled:opacity-40 text-white text-sm font-semibold transition-colors"
      >
        {loading ? "Simulating..." : "Simulate Strategy"}
      </button>

      {currentLap >= totalLaps - 1 && (
        <p className="text-xs text-gray-600 text-center">Race finished — no pit windows remaining</p>
      )}

      {/* Error */}
      {error && (
        <p className="text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}

      {/* Result */}
      {result && (
        <div className="bg-pitwall border border-border rounded-lg p-4 space-y-3">
          <p className="text-xs text-gray-400 leading-relaxed">{result.explanation}</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "Win %",    orig: result.original_win_pct,    next: result.new_win_pct,    delta: deltaWin    },
              { label: "Podium %", orig: result.original_podium_pct, next: result.new_podium_pct, delta: deltaPodium },
            ].map(({ label, orig, next, delta }) => (
              <div key={label} className="bg-panel rounded p-3">
                <p className="text-xs text-gray-500 mb-1">{label}</p>
                <p className="text-lg font-bold text-white">{next?.toFixed(1)}%</p>
                <p className="text-xs text-gray-500">was {orig?.toFixed(1)}%</p>
                <span className={`text-xs font-bold ${delta >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {delta >= 0 ? "+" : ""}{delta?.toFixed(1)} pp
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
