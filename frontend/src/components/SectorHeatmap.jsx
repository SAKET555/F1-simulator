import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

function sectorColor(val, min, max) {
  if (val == null) return "#1a1d27";
  const t = Math.max(0, Math.min(1, (val - min) / (max - min + 0.001)));
  if (t < 0.5) {
    const r = Math.round(34 + (234 - 34) * (t * 2));
    const g = Math.round(197 + (179 - 197) * (t * 2));
    return `rgb(${r},${g},34)`;
  } else {
    const r = Math.round(234 + (239 - 234) * ((t - 0.5) * 2));
    const g = Math.round(179 + (68 - 179) * ((t - 0.5) * 2));
    return `rgb(${r},${g},34)`;
  }
}

export default function SectorHeatmap({ raceId, cars = [] }) {
  const [driver, setDriver] = useState("");
  const [laps, setLaps] = useState([]);
  const [loading, setLoading] = useState(false);

  const drivers = [...new Set(cars.map(c => c.driver_code))];

  useEffect(() => {
    if (drivers.length > 0 && !driver) setDriver(drivers[0]);
  }, [cars]);

  function load() {
    if (!raceId || !driver) return;
    setLoading(true);
    fetch(`${API_BASE}/races/${raceId}/sectors?driver=${driver}`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => { setLaps(d.laps || []); setLoading(false); })
      .catch(() => { setLaps([]); setLoading(false); });
  }

  const validLaps = laps.filter(l => l.s1_s || l.s2_s || l.s3_s);
  const s1Vals = validLaps.map(l => l.s1_s).filter(Boolean);
  const s2Vals = validLaps.map(l => l.s2_s).filter(Boolean);
  const s3Vals = validLaps.map(l => l.s3_s).filter(Boolean);
  const s1Range = s1Vals.length ? [Math.min(...s1Vals), Math.max(...s1Vals)] : [0, 1];
  const s2Range = s2Vals.length ? [Math.min(...s2Vals), Math.max(...s2Vals)] : [0, 1];
  const s3Range = s3Vals.length ? [Math.min(...s3Vals), Math.max(...s3Vals)] : [0, 1];

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Sector Times</h3>
      <div className="flex items-center gap-2 mb-3">
        <select
          className="bg-pitwall border border-border rounded px-2 py-1 text-xs text-white"
          value={driver}
          onChange={e => setDriver(e.target.value)}
        >
          {drivers.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <button onClick={load} disabled={loading}
          className="px-3 py-1 bg-f1red text-white text-xs rounded hover:bg-red-700 disabled:opacity-50">
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {validLaps.length === 0 ? (
        <p className="text-gray-600 text-xs">Select a driver and click Load</p>
      ) : (
        <div className="overflow-auto max-h-64">
          <table className="text-xs w-full">
            <thead>
              <tr>
                <th className="text-left text-gray-500 pb-1 pr-2">Lap</th>
                <th className="text-center text-gray-500 pb-1 px-1">S1</th>
                <th className="text-center text-gray-500 pb-1 px-1">S2</th>
                <th className="text-center text-gray-500 pb-1 px-1">S3</th>
              </tr>
            </thead>
            <tbody>
              {validLaps.slice(-40).map(l => (
                <tr key={l.lap}>
                  <td className="text-gray-400 pr-2 py-0.5">{l.lap}</td>
                  {[["s1_s", s1Range], ["s2_s", s2Range], ["s3_s", s3Range]].map(([key, range]) => (
                    <td key={key} className="px-1 py-0.5 text-center rounded"
                      style={{ background: sectorColor(l[key], range[0], range[1]), color: "#000" }}>
                      {l[key] != null ? l[key].toFixed(3) : "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
