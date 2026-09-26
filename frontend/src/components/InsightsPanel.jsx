import { useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea, Legend,
} from "recharts";
import {
  Search, Gauge, Crosshair, Route, CircleDot, Flag, Trophy, Timer, Shuffle, Siren, Wrench, Sparkles,
} from "lucide-react";
import { API_BASE, TIRE_COLORS, getTeamColor } from "../lib/constants";

const EXAMPLES = [
  "who won the most races",
  "which race had the most overtaking",
  "safety car",
  "tyre degradation soft",
  "most retirements",
  "fastest pit stops",
];

const CAT = {
  Pace:          { color: "#22d3ee", icon: Gauge,     blurb: "How quick the cars and teams really were" },
  Consistency:   { color: "#a78bfa", icon: Crosshair, blurb: "Who kept it clean lap after lap" },
  Strategy:      { color: "#f59e0b", icon: Route,     blurb: "Stops, stints and the undercut game" },
  Tyres:         { color: "#f87171", icon: CircleDot, blurb: "Compound choice and how tyres aged" },
  "Race flow":   { color: "#34d399", icon: Flag,      blurb: "Lead changes, fights and retirements" },
};

const HIGHLIGHTS = [
  { id: "fastest_lap",     icon: Timer   },
  { id: "win_margin",      icon: Trophy  },
  { id: "lead_changes",    icon: Flag    },
  { id: "swaps",           icon: Shuffle },
  { id: "neutral",         icon: Siren   },
  { id: "median_pit_loss", icon: Wrench  },
];

const AXIS = { fill: "#727a90", fontSize: 10 };
const TOOLTIP = {
  contentStyle: { background: "#151824", border: "1px solid #2a2f40", borderRadius: 10, fontSize: 12 },
  labelStyle: { color: "#fff" },
};

const fmtLap = (s) => {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(3).padStart(6, "0")}`;
};

/* ── small building blocks ─────────────────────────────────────────────── */

function Card({ title, subtitle, children, className = "" }) {
  return (
    <section className={`card p-4 md:p-5 ${className}`}>
      <div className="mb-3">
        <h3>{title}</h3>
        {subtitle && <p className="text-[11px] text-ink-500 mt-1 leading-relaxed">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

function InsightCard({ item, color }) {
  return (
    <div className="relative rounded-xl bg-white/[.03] border border-white/[.07] px-3.5 py-3 min-w-0 hover:bg-white/[.06] transition-colors">
      <span className="absolute left-0 top-3 bottom-3 w-[3px] rounded-r" style={{ background: color }} />
      <p className="text-[10px] uppercase tracking-[.16em] text-ink-500 truncate" title={item.title}>{item.title}</p>
      <p className="display font-bold text-xl leading-tight break-words mt-0.5">{item.value}</p>
      {item.detail && <p className="text-[11px] text-ink-500 mt-1 leading-snug">{item.detail}</p>}
    </div>
  );
}

function CategorySection({ cat, items }) {
  if (!items.length) return null;
  const { color, icon: Icon, blurb } = CAT[cat] ?? { color: "#9ca3af", icon: Sparkles, blurb: "" };
  return (
    <section className="card p-4 md:p-5">
      <div className="flex items-center gap-3 mb-3">
        <span className="inline-flex items-center justify-center w-9 h-9 rounded-xl" style={{ background: `${color}22`, color }}>
          <Icon size={18} />
        </span>
        <div>
          <h3 className="no-tick">{cat} <span className="text-ink-500 normal-case tracking-normal font-sans font-medium text-xs">· {items.length}</span></h3>
          <p className="text-[11px] text-ink-500">{blurb}</p>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
        {items.map(i => <InsightCard key={i.id} item={i} color={color} />)}
      </div>
    </section>
  );
}

/* ── visuals built from the structured "extras" ────────────────────────── */

function StrategyTimeline({ strategy, total, neutral }) {
  if (!strategy?.length) return null;
  const pos = (lap) => `${((lap - 1) / total) * 100}%`;
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[560px]">
        {/* lap ruler */}
        <div className="flex items-center gap-2 mb-1 pl-[88px] pr-2">
          <div className="relative flex-1 h-4">
            {Array.from({ length: Math.floor(total / 10) + 1 }, (_, i) => i * 10).filter(l => l > 0 && l <= total).map(l => (
              <span key={l} className="absolute text-[9px] text-ink-500 mono -translate-x-1/2" style={{ left: pos(l + 0.5) }}>{l}</span>
            ))}
          </div>
        </div>
        <div className="space-y-1">
          {strategy.map(row => (
            <div key={row.driver} className={`flex items-center gap-2 ${row.status === "DNF" ? "opacity-60" : ""}`}>
              <div className="w-[80px] flex items-center gap-1.5 flex-shrink-0">
                <span className="mono text-[10px] text-ink-500 w-4 text-right">{row.status === "DNF" ? "–" : row.position}</span>
                <span className="w-[3px] h-4 rounded" style={{ background: getTeamColor(row.team) }} />
                <span className="display font-extrabold text-[15px] tracking-wider">{row.driver}</span>
              </div>
              <div className="relative flex-1 h-6 rounded-md bg-white/[.04] overflow-hidden">
                {neutral.map(l => (
                  <span key={l} className="absolute top-0 bottom-0 bg-amber-400/20 z-[1]"
                    style={{ left: pos(l), width: `${100 / total}%` }} />
                ))}
                {row.stints.map((s, i) => {
                  const c = TIRE_COLORS[s.compound] ?? TIRE_COLORS.UNKNOWN;
                  return (
                    <div
                      key={i}
                      title={`${row.driver} · ${s.compound.toLowerCase()} · laps ${s.start}–${s.end} (${s.laps})`}
                      className="absolute top-[3px] bottom-[3px] rounded flex items-center justify-center text-[10px] font-extrabold mono overflow-hidden z-[2]"
                      style={{ left: pos(s.start), width: `calc(${(s.laps / total) * 100}% - 2px)`, background: c.hex, color: s.compound === "HARD" || s.compound === "MEDIUM" ? "#111" : "#fff" }}
                    >
                      {s.laps >= 5 ? `${c.label} ${s.laps}` : ""}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 mt-3 pl-[88px] text-[10px] text-ink-500">
          {["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"].map(k => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: TIRE_COLORS[k].hex }} />{k.charAt(0) + k.slice(1).toLowerCase()}
            </span>
          ))}
          {neutral.length > 0 && (
            <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-amber-400/40" />Neutralised</span>
          )}
        </div>
      </div>
    </div>
  );
}

function PaceRanking({ rows }) {
  if (!rows?.length) return <p className="text-ink-500 text-sm">Not enough clean laps to rank pace.</p>;
  const max = Math.max(...rows.map(r => r.delta_s), 0.001);
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={r.driver} className="flex items-center gap-2 text-xs">
          <span className="mono text-ink-500 w-5 text-right">{i + 1}</span>
          <span className="display font-extrabold text-[15px] tracking-wider w-9">{r.driver}</span>
          <div className="flex-1 h-4 rounded bg-white/[.04] overflow-hidden">
            <div className="h-full rounded" style={{ width: `${Math.max((r.delta_s / max) * 100, 2)}%`, background: getTeamColor(r.team) }} />
          </div>
          <span className="mono text-ink-300 w-14 text-right">{r.delta_s === 0 ? "fastest" : `+${r.delta_s.toFixed(2)}s`}</span>
          <span className="mono text-ink-500 w-16 text-right hidden md:inline">±{r.consistency?.toFixed(2)}s</span>
        </div>
      ))}
      <p className="text-[10px] text-ink-500 pt-1">Median clean-lap gap to the quickest driver · right column = consistency.</p>
    </div>
  );
}

function FieldPace({ data, neutral }) {
  if (!data?.length) return null;
  const vals = data.map(d => d.median_s).sort((a, b) => a - b);
  const lo = vals[0], hi = vals[Math.floor(vals.length * 0.97)] ?? vals[vals.length - 1];
  return (
    <ResponsiveContainer width="100%" height={400}>
      <LineChart data={data} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
        <CartesianGrid stroke="#262b3a" strokeDasharray="3 3" />
        <XAxis dataKey="lap" tick={AXIS} tickLine={false} axisLine={{ stroke: "#2a2f40" }} />
        <YAxis domain={[Math.floor(lo - 0.5), Math.ceil(hi + 0.5)]} allowDataOverflow tick={AXIS} tickLine={false} axisLine={false} width={40}
          tickFormatter={(v) => fmtLap(v).replace(/\.000$/, "")} />
        <Tooltip {...TOOLTIP} formatter={(v) => [fmtLap(v), "Field median"]} labelFormatter={(l) => `Lap ${l}`} />
        {neutral.map(l => <ReferenceArea key={l} x1={l - 0.5} x2={l + 0.5} fill="#f59e0b" fillOpacity={0.18} strokeOpacity={0} />)}
        <Line type="monotone" dataKey="median_s" stroke="#22d3ee" strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function DegCurves({ curves }) {
  const comps = Object.keys(curves ?? {});
  if (!comps.length) return <p className="text-ink-500 text-sm">Not enough laps on any compound to draw a wear curve.</p>;
  const ages = [...new Set(comps.flatMap(c => curves[c].map(p => p.age)))].sort((a, b) => a - b);
  const data = ages.map(age => {
    const row = { age };
    comps.forEach(c => { const p = curves[c].find(x => x.age === age); if (p) row[c] = p.delta_s; });
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={230}>
      <LineChart data={data} margin={{ left: 0, right: 8, top: 6, bottom: 0 }}>
        <CartesianGrid stroke="#262b3a" strokeDasharray="3 3" />
        <XAxis dataKey="age" tick={AXIS} tickLine={false} axisLine={{ stroke: "#2a2f40" }} label={{ value: "tyre age (laps)", fill: "#727a90", fontSize: 10, dy: 12 }} height={34} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`} />
        <Tooltip {...TOOLTIP} formatter={(v, n) => [`${v > 0 ? "+" : ""}${v.toFixed(2)}s`, n.charAt(0) + n.slice(1).toLowerCase()]} labelFormatter={(l) => `Tyre age ~${l} laps`} />
        <Legend formatter={(v) => <span className="text-xs text-ink-300">{v.charAt(0) + v.slice(1).toLowerCase()}</span>} />
        {comps.map(c => (
          <Line key={c} type="monotone" dataKey={c} stroke={TIRE_COLORS[c]?.hex ?? "#9ca3af"} strokeWidth={2.2}
            dot={{ r: 2.5 }} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function LeadTimeline({ segments, total, teamOf }) {
  if (!segments?.length) return null;
  const led = {};
  segments.forEach(s => { led[s.driver] = (led[s.driver] ?? 0) + (s.end - s.start + 1); });
  return (
    <div>
      <div className="flex h-8 rounded-lg overflow-hidden bg-white/[.04]">
        {segments.map((s, i) => {
          const w = ((s.end - s.start + 1) / total) * 100;
          return (
            <div key={i} title={`${s.driver} led laps ${s.start}–${s.end}`}
              className="flex items-center justify-center text-[10px] font-extrabold border-r border-black/40 last:border-r-0 overflow-hidden"
              style={{ width: `${w}%`, background: getTeamColor(teamOf[s.driver]), color: "#0b0d13" }}>
              {w > 5 ? s.driver : ""}
            </div>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-xs">
        {Object.entries(led).sort((a, b) => b[1] - a[1]).map(([d, n]) => (
          <span key={d} className="inline-flex items-center gap-1.5 text-ink-300">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: getTeamColor(teamOf[d]) }} />
            <span className="font-bold text-white">{d}</span> <span className="mono">{n} {n === 1 ? "lap" : "laps"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function TeamTable({ teams }) {
  if (!teams?.length) return null;
  const vals = teams.map(t => t.median_delta_s).filter(v => v != null);
  const maxAbs = Math.max(...vals.map(Math.abs), 0.001);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-ink-500 text-left border-b border-white/10">
            <th className="pb-2 pr-3 font-medium">Team</th>
            <th className="pb-2 pr-3 font-medium hidden sm:table-cell">Drivers</th>
            <th className="pb-2 pr-3 font-medium text-right">Best P</th>
            <th className="pb-2 pr-3 font-medium min-w-[140px]">Pace vs field</th>
            <th className="pb-2 pr-3 font-medium text-right hidden md:table-cell">Spread</th>
            <th className="pb-2 pr-3 font-medium text-right">Stops</th>
            <th className="pb-2 pr-3 font-medium text-right">DNF</th>
            <th className="pb-2 font-medium text-right">Best lap</th>
          </tr>
        </thead>
        <tbody>
          {teams.map(t => {
            const col = getTeamColor(t.team);
            const d = t.median_delta_s;
            return (
              <tr key={t.team} className="border-b border-white/5 hover:bg-white/[.03]">
                <td className="py-2 pr-3">
                  <span className="inline-flex items-center gap-2">
                    <span className="w-[3px] h-5 rounded" style={{ background: col }} />
                    <span className="font-semibold text-white">{t.team}</span>
                  </span>
                </td>
                <td className="py-2 pr-3 text-ink-300 hidden sm:table-cell">{t.drivers.join(" · ")}</td>
                <td className="py-2 pr-3 text-right mono">{t.best_position}</td>
                <td className="py-2 pr-3">
                  {d == null ? <span className="text-ink-500">—</span> : (
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1 h-2 rounded bg-white/[.05]">
                        <span className="absolute top-0 bottom-0 left-1/2 w-px bg-white/25" />
                        <span className="absolute top-0 bottom-0 rounded"
                          style={{ background: col, width: `${(Math.abs(d) / maxAbs) * 50}%`, [d < 0 ? "right" : "left"]: "50%" }} />
                      </div>
                      <span className={`mono w-14 text-right ${d < 0 ? "text-emerald-400" : "text-red-300"}`}>{d > 0 ? "+" : ""}{d.toFixed(2)}s</span>
                    </div>
                  )}
                </td>
                <td className="py-2 pr-3 text-right mono text-ink-300 hidden md:table-cell">{t.consistency_s != null ? `±${t.consistency_s.toFixed(2)}` : "—"}</td>
                <td className="py-2 pr-3 text-right mono">{t.stops}</td>
                <td className={`py-2 pr-3 text-right mono ${t.dnfs ? "text-red-300" : "text-ink-500"}`}>{t.dnfs}</td>
                <td className="py-2 text-right mono text-ink-300">{t.best_lap ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── Ask the season ────────────────────────────────────────────────────── */

function AskTheSeason({ year }) {
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("season");          // "season" | "all"
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [cov, setCov] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/rag/coverage`).then(r => r.ok ? r.json() : null).then(setCov).catch(() => {});
  }, []);

  function ask(text) {
    const query = (text ?? q).trim();
    if (query.length < 2) return;
    setQ(query);
    setBusy(true);
    setErr(null);
    const params = new URLSearchParams({ q: query, limit: "8" });
    if (scope === "season" && year) params.set("year", String(year));
    fetch(`${API_BASE}/rag/search?${params}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setRes)
      .catch(e => setErr(String(e)))
      .finally(() => setBusy(false));
  }

  const yearCov = cov?.seasons?.find(s => s.year === year);

  return (
    <section className="card relative overflow-hidden p-4 md:p-5">
      <div className="absolute -left-16 -bottom-20 w-64 h-64 rounded-full bg-violet-500/10 blur-3xl pointer-events-none" />
      <div className="relative">
        <h3>Ask the season</h3>
        <p className="text-[11px] text-ink-500 mt-1 mb-3 leading-relaxed">
          Searches statistics computed from locally cached race data. It retrieves the best-matching facts — it does not
          write answers, so every line below is a real computed number.
          {yearCov && ` ${year}: ${yearCov.races_indexed} of ${yearCov.races_in_calendar} races indexed.`}
        </p>

        <form onSubmit={e => { e.preventDefault(); ask(); }} className="flex gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[220px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              placeholder="e.g. which race had the most safety cars?"
              className="w-full bg-white/[.04] border border-white/10 rounded-xl pl-9 pr-3 py-2.5 text-sm text-white placeholder-ink-500 focus:outline-none focus:border-f1red/60 transition-colors"
            />
          </div>
          <select
            value={scope}
            onChange={e => setScope(e.target.value)}
            className="bg-white/[.04] border border-white/10 rounded-xl px-3 text-sm text-ink-300"
          >
            <option value="season">{year} only</option>
            <option value="all">All seasons</option>
          </select>
          <button type="submit" className="px-5 py-2.5 bg-f1red hover:bg-red-600 rounded-xl text-white text-sm font-bold transition-colors shadow-glow">
            Ask
          </button>
        </form>

        <div className="flex gap-1.5 flex-wrap mt-2.5">
          {EXAMPLES.map(ex => (
            <button key={ex} onClick={() => ask(ex)}
              className="text-[11px] text-ink-300 hover:text-white border border-white/10 hover:border-white/30 bg-white/[.03] rounded-full px-3 py-1 transition-colors">
              {ex}
            </button>
          ))}
        </div>

        <div className="mt-4 space-y-2">
          {busy && Array.from({ length: 3 }).map((_, i) => <div key={i} className="skeleton h-12" />)}
          {err && <p className="text-red-400 text-sm">Search failed ({err}).</p>}
          {!busy && res && res.results.length === 0 && (
            <p className="text-ink-500 text-sm">Nothing matched. Try other words, e.g. a driver code, a circuit or a topic like “pit stops”.</p>
          )}
          {!busy && res?.results.map((h, i) => (
            <div key={i} className="rounded-xl bg-white/[.04] border border-white/[.07] px-3.5 py-2.5 animate-fadeUp">
              <p className="text-sm text-ink-50 leading-snug">{h.text}</p>
              <p className="text-[10px] text-ink-500 mt-1.5 flex items-center gap-2">
                <span className="chip !py-0 !text-[9px]">{h.kind === "season" ? "Season roll-up" : h.category}</span>
                {h.source}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ── panel ─────────────────────────────────────────────────────────────── */

export default function InsightsPanel({ raceId, year }) {
  const [race, setRace] = useState(null);
  const [season, setSeason] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!raceId) return;
    setRace(null); setSeason(null); setError(null);
    fetch(`${API_BASE}/races/${raceId}/insights`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setRace)
      .catch(e => setError(String(e)));
  }, [raceId]);

  useEffect(() => {
    if (!year) return;
    fetch(`${API_BASE}/seasons/${year}/insights`)
      .then(r => r.ok ? r.json() : null)
      .then(setSeason)
      .catch(() => setSeason(null));
  }, [year]);

  const byId = useMemo(() => Object.fromEntries((race?.insights ?? []).map(i => [i.id, i])), [race]);
  const teamOf = useMemo(
    () => Object.fromEntries((race?.extras?.strategy ?? []).map(s => [s.driver, s.team])),
    [race],
  );

  if (!raceId) return <p className="text-ink-500 text-sm">Historical races only</p>;
  if (error) return <p className="text-red-400 text-sm">Couldn't build insights for this race ({error}).</p>;
  if (!race) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-28" />
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-24" />)}
        </div>
        <div className="skeleton h-72" />
      </div>
    );
  }

  const ex = race.extras;
  const cats = race.categories ?? [];
  const highlights = HIGHLIGHTS.map(h => ({ ...h, item: byId[h.id] })).filter(h => h.item);

  return (
    <div className="space-y-4">
      {/* Hero */}
      <section className="card relative overflow-hidden p-5">
        <div className="absolute -right-10 -top-14 w-64 h-64 rounded-full bg-f1red/10 blur-3xl pointer-events-none" />
        <div className="relative flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="display font-semibold text-xs tracking-[.3em] text-f1red uppercase">Deep-dive analytics</p>
            <h2 className="no-tick !text-white !tracking-normal !normal-case display font-extrabold mt-1" style={{ fontSize: "2rem" }}>
              {race.year} {race.event_name}
            </h2>
            <p className="text-xs text-ink-500 mt-1.5 max-w-2xl leading-relaxed">
              Computed from lap timing. Neutralised laps are excluded from pace figures; overtakes, undercuts and pit-stop
              losses are estimates from lap order.
            </p>
          </div>
          <div className="flex gap-2">
            <span className="chip"><Sparkles size={11} />{race.insights.length} analyses</span>
            {ex?.neutral_laps?.length > 0 && <span className="chip !text-amber-300 !border-amber-500/30">{ex.neutral_laps.length} neutralised laps</span>}
          </div>
        </div>
      </section>

      {race.insights.length === 0 ? (
        <p className="text-ink-500 text-sm">This session has no timed racing laps, so there is nothing to analyse.</p>
      ) : (
        <>
          {/* Highlights */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            {highlights.map(({ id, icon: Icon, item }) => (
              <div key={id} className="card p-3.5 relative overflow-hidden">
                <Icon size={15} className="text-f1red mb-2" />
                <p className="text-[10px] uppercase tracking-[.16em] text-ink-500 truncate">{item.title}</p>
                <p className="display font-extrabold text-2xl leading-tight break-words">{item.value}</p>
                <p className="text-[10px] text-ink-500 mt-1 leading-snug line-clamp-2">{item.detail}</p>
              </div>
            ))}
          </div>

          {ex && (
            <>
              <Card
                title="Strategy timeline"
                subtitle="Every driver's stints, in finishing order. Bar colour is the tyre; the number is stint length in laps. Amber columns are neutralised laps."
              >
                <StrategyTimeline strategy={ex.strategy} total={ex.total_laps} neutral={ex.neutral_laps} />
              </Card>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <Card title="Race pace ranking" subtitle="Median clean lap, measured against the quickest driver.">
                  <PaceRanking rows={ex.pace_ranking} />
                </Card>
                <Card title="Field pace by lap" subtitle="Median lap time of the whole field on every green-flag lap. Spikes are safety cars; the downward drift is fuel burn and track rubber.">
                  <FieldPace data={ex.field_pace} neutral={ex.neutral_laps} />
                </Card>
                <Card title="Tyre wear curves" subtitle="Pace against the field on the same lap, by tyre age. A steeper climb means the compound fades faster. Indicative, not a controlled test.">
                  <DegCurves curves={ex.deg_curves} />
                </Card>
                <Card title="Who led when" subtitle="The race leader at the end of every lap.">
                  <LeadTimeline segments={ex.lead_timeline} total={ex.total_laps} teamOf={teamOf} />
                </Card>
              </div>

              <Card title="Team scorecard" subtitle="Pace is each team's median lap against the field's median on the same lap (negative = faster). Spread is average lap-to-lap variation.">
                <TeamTable teams={ex.teams} />
              </Card>
            </>
          )}

          <AskTheSeason year={year} />

          {cats.map(cat => (
            <CategorySection key={cat} cat={cat} items={race.insights.filter(i => i.category === cat)} />
          ))}
        </>
      )}

      {season && season.insights.length > 0 && (
        <section className="card p-4 md:p-5">
          <div className="mb-3">
            <h3>{season.year} season roll-up</h3>
            <p className="text-[11px] text-ink-500 mt-1">{season.races_analysed} races analysed from the local cache.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
            {season.insights.map(i => <InsightCard key={i.id} item={i} color="#e10600" />)}
          </div>
        </section>
      )}
    </div>
  );
}
