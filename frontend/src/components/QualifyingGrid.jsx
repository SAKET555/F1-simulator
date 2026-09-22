import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

function fmtTime(s) {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(3).padStart(6, "0");
  return `${m}:${sec}`;
}

export default function QualifyingGrid({ raceId }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!raceId) return;
    setLoading(true);
    fetch(`${API_BASE}/races/${raceId}/qualifying`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => { setResults(d); setLoading(false); })
      .catch(() => { setResults([]); setLoading(false); });
  }, [raceId]);

  if (loading) return (
    <div className="flex items-center justify-center h-32 text-gray-600 text-sm">Loading qualifying…</div>
  );

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Qualifying</h3>
      {results.length === 0 ? (
        <p className="text-gray-600 text-xs">No qualifying data available</p>
      ) : (
        <div className="overflow-auto max-h-80">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-border">
                <th className="text-left pb-1 pr-2">P</th>
                <th className="text-left pb-1 pr-2">Driver</th>
                <th className="text-left pb-1 pr-2">Team</th>
                <th className="text-right pb-1 pr-2">Q1</th>
                <th className="text-right pb-1 pr-2">Q2</th>
                <th className="text-right pb-1">Q3</th>
              </tr>
            </thead>
            <tbody>
              {results.map(r => (
                <tr key={r.driver_code} className="border-b border-border/30 hover:bg-white/5">
                  <td className="py-1 pr-2 text-gray-400">{r.position}</td>
                  <td className="py-1 pr-2 font-bold text-white">{r.driver_code}</td>
                  <td className="py-1 pr-2 text-gray-500 truncate max-w-[80px]">{r.team}</td>
                  <td className={`py-1 pr-2 text-right font-mono ${r.q1_s ? "text-gray-300" : "text-gray-600"}`}>
                    {fmtTime(r.q1_s)}
                  </td>
                  <td className={`py-1 pr-2 text-right font-mono ${r.q2_s ? "text-gray-300" : "text-gray-600"}`}>
                    {fmtTime(r.q2_s)}
                  </td>
                  <td className={`py-1 text-right font-mono ${r.q3_s ? "text-yellow-400 font-bold" : "text-gray-600"}`}>
                    {fmtTime(r.q3_s)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
