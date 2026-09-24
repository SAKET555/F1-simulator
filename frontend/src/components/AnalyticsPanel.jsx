import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";
import CircuitImage from "./CircuitImage";

function StatCard({ label, value, sub }) {
  return (
    <div className="bg-pitwall border border-border rounded-lg px-3 py-2.5 min-w-0">
      <p className="text-[10px] uppercase tracking-widest text-gray-500">{label}</p>
      <p className="text-white font-black text-lg leading-tight truncate">{value}</p>
      {sub && <p className="text-[11px] text-gray-500 truncate" title={sub}>{sub}</p>}
    </div>
  );
}

function DriverTable({ rows }) {
  return (
    <div className="overflow-auto max-h-[28rem]">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-panel">
          <tr className="text-gray-500 border-b border-border text-left">
            <th className="pb-1.5 pr-2 w-8">P</th>
            <th className="pb-1.5 pr-2">Driver</th>
            <th className="pb-1.5 pr-2">Status</th>
            <th className="pb-1.5 pr-2 text-right">Best lap</th>
            <th className="pb-1.5 pr-2 text-right">Median pace</th>
            <th className="pb-1.5 pr-2 text-right" title="Lap-time spread vs. the field; lower is steadier">Consistency</th>
            <th className="pb-1.5 pr-2 text-right">Stops</th>
            <th className="pb-1.5 text-right" title="Versus position after lap 1">Places ±</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.driver_code} className={`border-b border-border/30 hover:bg-white/5 ${r.status === "DNF" ? "opacity-50" : ""}`}>
              <td className="py-1 pr-2 text-gray-400">{r.status === "DNF" ? "—" : r.position}</td>
              <td className="py-1 pr-2" style={{ borderLeft: `3px solid ${r.color}` }}>
                <span className="pl-2 font-bold text-white">{r.driver_code}</span>
                <span className="pl-2 text-gray-600 hidden md:inline">{r.team}</span>
              </td>
              <td className="py-1 pr-2 text-gray-400">{r.status}</td>
              <td className={`py-1 pr-2 text-right font-mono ${r.is_fastest ? "text-purple-400 font-bold" : "text-gray-300"}`}>{r.best_lap ?? "—"}</td>
              <td className="py-1 pr-2 text-right font-mono text-gray-300">{r.median_pace ?? "—"}</td>
              <td className="py-1 pr-2 text-right font-mono text-gray-300">{r.consistency != null ? `±${r.consistency.toFixed(2)}s` : "—"}</td>
              <td className="py-1 pr-2 text-right text-gray-300">{r.stops}</td>
              <td className={`py-1 text-right font-mono font-bold ${r.places_gained > 0 ? "text-green-400" : r.places_gained < 0 ? "text-red-400" : "text-gray-600"}`}>
                {r.places_gained == null ? "—" : r.places_gained > 0 ? `+${r.places_gained}` : r.places_gained}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartCard({ raceId, chart }) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const url = `${API_BASE}/races/${raceId}/analytics/charts/${chart.id}.png`;

  return (
    <div className="bg-panel border border-border rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">{chart.title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="text-[11px] text-gray-600 hover:text-white flex-shrink-0">
          open full size ↗
        </a>
      </div>
      <p className="text-[11px] text-gray-500 leading-relaxed">{chart.caption}</p>
      {failed ? (
        <div className="text-red-400/80 text-xs py-10 text-center">Couldn't render this chart</div>
      ) : (
        <div className="relative">
          {!loaded && <div className="absolute inset-0 flex items-center justify-center text-gray-600 text-xs">Rendering…</div>}
          <img
            src={url}
            alt={chart.title}
            loading="lazy"
            className={`w-full rounded-lg transition-opacity ${loaded ? "opacity-100" : "opacity-0 min-h-48"}`}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
          />
        </div>
      )}
    </div>
  );
}

export default function AnalyticsPanel({ raceId }) {
  const [summary, setSummary] = useState(null);
  const [charts, setCharts] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!raceId) return;
    setSummary(null);
    setError(null);
    fetch(`${API_BASE}/races/${raceId}/analytics/summary`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setSummary)
      .catch(e => setError(String(e)));
    fetch(`${API_BASE}/races/${raceId}/analytics/charts`)
      .then(r => r.ok ? r.json() : [])
      .then(setCharts)
      .catch(() => setCharts([]));
  }, [raceId]);

  if (!raceId) return <p className="text-gray-600 text-sm">Historical races only</p>;
  if (error) return <p className="text-red-400 text-sm">Couldn't build analytics for this race ({error}).</p>;
  if (!summary) return <p className="text-gray-500 text-sm py-10 text-center">Crunching the race…</p>;

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-gray-600">
        Full-race analysis of {summary.year} {summary.event_name} — computed in Python (pandas) and drawn with matplotlib.
        Safety-car / VSC laps are detected from the field and excluded from pace figures.
      </p>

      <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-4">
        <div className="bg-panel border border-border rounded-xl p-4">
          <CircuitImage raceId={raceId} />
        </div>
        <div className="bg-panel border border-border rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Race in numbers</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {summary.cards.map(c => <StatCard key={c.label} {...c} />)}
          </div>
        </div>
      </div>

      <div className="bg-panel border border-border rounded-xl p-4">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Driver breakdown</h3>
        <DriverTable rows={summary.drivers} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {charts.map(c => <ChartCard key={c.id} raceId={raceId} chart={c} />)}
      </div>
    </div>
  );
}
