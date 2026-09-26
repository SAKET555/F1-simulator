import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";
import CircuitImage from "./CircuitImage";
import { Trophy, Timer, Flag, Shuffle, Siren, Wrench, Gauge, Crosshair, CircleDot, ArrowUpRight, ArrowDownRight, Users } from "lucide-react";

const CARD_ICONS = {
  "Winner": Trophy, "Fastest lap": Timer, "Finishers / DNF": Flag, "Lead changes": Shuffle,
  "Neutralised laps": Siren, "Pit stops": Wrench, "Median stop loss": Wrench,
  "Most places gained": ArrowUpRight, "Most places lost": ArrowDownRight,
  "Best race pace": Gauge, "Most consistent": Crosshair, "Most-used tyre": CircleDot,
};

function StatCard({ label, value, sub }) {
  const Icon = CARD_ICONS[label] ?? Users;
  return (
    <div className="relative rounded-xl bg-white/[.03] border border-white/[.07] px-3.5 py-3 min-w-0 hover:bg-white/[.06] transition-colors">
      <div className="flex items-center gap-1.5 text-ink-500">
        <Icon size={12} className="text-f1red flex-shrink-0" />
        <p className="text-[10px] uppercase tracking-[.16em] truncate">{label}</p>
      </div>
      <p className="display font-extrabold text-2xl leading-tight truncate mt-0.5">{value}</p>
      {sub && <p className="text-[11px] text-ink-500 truncate" title={sub}>{sub}</p>}
    </div>
  );
}

function Podium({ rows }) {
  const top = rows.filter(r => r.status !== "DNF").slice(0, 3);
  if (top.length < 3) return null;
  // Classic podium order: P2, P1, P3
  const order = [top[1], top[0], top[2]];
  const height = { 1: "h-24", 2: "h-16", 3: "h-12" };
  return (
    <div className="grid grid-cols-3 gap-2 items-end">
      {order.map(r => (
        <div key={r.driver_code} className="text-center">
          <p className="display font-extrabold text-2xl leading-none">{r.driver_code}</p>
          <p className="text-[10px] text-ink-500 truncate mb-1.5">{r.team}</p>
          <div
            className={`${height[r.position] ?? "h-12"} rounded-t-lg flex items-start justify-center pt-2 display font-extrabold text-3xl`}
            style={{ background: `linear-gradient(180deg, ${r.color}, ${r.color}33)`, color: "#0b0d13" }}
          >
            {r.position}
          </div>
        </div>
      ))}
    </div>
  );
}

function DriverTable({ rows }) {
  return (
    <div className="overflow-auto max-h-[30rem] rounded-lg">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[#171a25] z-10">
          <tr className="text-ink-500 border-b border-white/10 text-left">
            <th className="pb-2 pr-2 w-8 font-medium">P</th>
            <th className="pb-2 pr-2 font-medium">Driver</th>
            <th className="pb-2 pr-2 font-medium">Status</th>
            <th className="pb-2 pr-2 text-right font-medium">Best lap</th>
            <th className="pb-2 pr-2 text-right font-medium">Median pace</th>
            <th className="pb-2 pr-2 text-right font-medium" title="Lap-time spread vs. the field; lower is steadier">Consistency</th>
            <th className="pb-2 pr-2 text-right font-medium">Stops</th>
            <th className="pb-2 text-right font-medium" title="Versus position after lap 1">Places ±</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.driver_code} className={`border-b border-white/5 hover:bg-white/[.04] ${r.status === "DNF" ? "opacity-50" : ""}`}>
              <td className="py-1.5 pr-2 mono text-ink-300">{r.status === "DNF" ? "—" : r.position}</td>
              <td className="py-1.5 pr-2">
                <span className="inline-flex items-center gap-2">
                  <span className="w-[3px] h-5 rounded" style={{ background: r.color }} />
                  <span className="display font-extrabold text-[15px] tracking-wider">{r.driver_code}</span>
                  <span className="text-ink-500 hidden md:inline">{r.team}</span>
                </span>
              </td>
              <td className="py-1.5 pr-2 text-ink-300">{r.status}</td>
              <td className={`py-1.5 pr-2 text-right mono ${r.is_fastest ? "text-purple-300 font-bold" : "text-ink-300"}`}>
                {r.is_fastest && <span className="mr-1.5 text-[9px] bg-purple-500/20 border border-purple-400/30 px-1 rounded">FL</span>}
                {r.best_lap ?? "—"}
              </td>
              <td className="py-1.5 pr-2 text-right mono text-ink-300">{r.median_pace ?? "—"}</td>
              <td className="py-1.5 pr-2 text-right mono text-ink-300">{r.consistency != null ? `±${r.consistency.toFixed(2)}s` : "—"}</td>
              <td className="py-1.5 pr-2 text-right mono text-ink-300">{r.stops}</td>
              <td className={`py-1.5 text-right mono font-bold ${r.places_gained > 0 ? "text-emerald-400" : r.places_gained < 0 ? "text-red-400" : "text-ink-500"}`}>
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
    <div className="card p-4 flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3>{chart.title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="text-[11px] text-ink-500 hover:text-white flex-shrink-0 transition-colors">
          full size ↗
        </a>
      </div>
      <p className="text-[11px] text-ink-500 leading-relaxed">{chart.caption}</p>
      {failed ? (
        <div className="text-red-400/80 text-xs py-10 text-center">Couldn't render this chart</div>
      ) : (
        <div className="relative">
          {!loaded && <div className="skeleton absolute inset-0 min-h-48" />}
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

  if (!raceId) return <p className="text-ink-500 text-sm">Historical races only</p>;
  if (error) return <p className="text-red-400 text-sm">Couldn't build analytics for this race ({error}).</p>;
  if (!summary) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-24" />
        <div className="grid xl:grid-cols-[420px_1fr] gap-4"><div className="skeleton h-72" /><div className="skeleton h-72" /></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <section className="card relative overflow-hidden p-5">
        <div className="absolute -right-10 -top-14 w-64 h-64 rounded-full bg-f1red/10 blur-3xl pointer-events-none" />
        <div className="relative">
          <p className="display font-semibold text-xs tracking-[.3em] text-f1red uppercase">Full-race analysis</p>
          <p className="display font-extrabold text-3xl leading-tight mt-1">{summary.year} {summary.event_name}</p>
          <p className="text-xs text-ink-500 mt-1.5 max-w-3xl leading-relaxed">
            Computed in Python (pandas) and drawn with matplotlib. Safety-car / VSC laps are detected from the field and
            excluded from pace figures{summary.neutral_laps?.length ? ` (${summary.neutral_laps.length} such laps in this race)` : ""}.
          </p>
        </div>
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-4">
        <div className="space-y-4">
          <div className="card p-4"><CircuitImage raceId={raceId} /></div>
          <div className="card p-4">
            <h3 className="mb-4">Podium</h3>
            <Podium rows={summary.drivers} />
          </div>
        </div>
        <div className="card p-4">
          <h3 className="mb-3">Race in numbers</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
            {summary.cards.map(c => <StatCard key={c.label} {...c} />)}
          </div>
        </div>
      </div>

      <div className="card p-4">
        <h3 className="mb-3">Driver breakdown</h3>
        <DriverTable rows={summary.drivers} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {charts.map(c => <ChartCard key={c.id} raceId={raceId} chart={c} />)}
      </div>
    </div>
  );
}
