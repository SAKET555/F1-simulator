import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";
import { Clock, Search, Database, CalendarDays, MapPin, Flag, Sparkles } from "lucide-react";

function Stat({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-2xl bg-white/[.04] border border-white/[.08]">
      <span className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-f1red/15 text-f1red">
        <Icon size={17} />
      </span>
      <div className="leading-tight">
        <p className="display font-extrabold text-2xl mono">{value}</p>
        <p className="text-[10px] uppercase tracking-[.2em] text-ink-500">{label}</p>
      </div>
    </div>
  );
}

export default function RaceSelector({ onSelect }) {
  const [races,        setRaces]        = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState(null);
  const [season,       setSeason]       = useState(null);
  const [searchQuery,  setSearchQuery]  = useState("");

  // Load race catalogue
  useEffect(() => {
    fetch(`${API_BASE}/races`)
      .then((r) => { if (!r.ok) throw new Error("Failed to load races"); return r.json(); })
      .then((data) => {
        setRaces(data);
        // Default to newest season with data
        const years = [...new Set(data.map((r) => r.year))].sort((a, b) => b - a);
        if (years.length) setSeason(years[0]);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="skeleton h-32" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton h-28" />)}
        </div>
      </div>
    );
  }
  if (error) return <p className="text-red-400 text-sm p-6">{error}</p>;

  const years = [...new Set(races.map((r) => r.year))].sort((a, b) => b - a);
  const seasonRaces = races.filter((r) => r.year === season);
  const filtered = seasonRaces.filter(r =>
    !searchQuery ||
    r.circuit?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    r.event_name?.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const cachedCount = races.filter(r => r.cached).length;
  const cachedInSeason = seasonRaces.filter(r => r.cached).length;

  return (
    <div className="flex flex-col gap-6">
      {/* Hero */}
      <section className="card relative overflow-hidden p-6 md:p-8">
        <div className="absolute -right-16 -top-20 w-96 h-96 rounded-full bg-f1red/15 blur-3xl pointer-events-none" />
        <div
          className="absolute right-6 bottom-0 top-0 w-1/3 opacity-[.07] pointer-events-none hidden md:block"
          style={{ background: "repeating-linear-gradient(-60deg, #fff 0 2px, transparent 2px 18px)" }}
        />
        <div className="relative">
          <p className="display font-semibold text-xs tracking-[.4em] text-f1red uppercase">Race &amp; strategy simulator</p>
          <h1 className="display font-extrabold text-5xl md:text-6xl leading-[.95] mt-2">
            <span className="text-f1red">SAK</span> RACING SIM
          </h1>
          <p className="text-ink-300 text-sm mt-3 max-w-xl leading-relaxed">
            Replay any race lap by lap, watch win probabilities update with Monte&nbsp;Carlo, test pit-stop what-ifs,
            and dig into pace, tyre and strategy analytics.
          </p>
          <div className="flex flex-wrap gap-3 mt-5">
            <Stat icon={Flag}         label="Races"          value={races.length} />
            <Stat icon={CalendarDays} label="Seasons"        value={years.length} />
            <Stat icon={Database}     label="Cached offline" value={cachedCount} />
            <Stat icon={Sparkles}     label="Analyses / race" value="45+" />
          </div>
        </div>
      </section>

      {/* Season tabs + search */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5 flex-wrap">
          {years.map((y) => (
            <button
              key={y}
              onClick={() => setSeason(y)}
              className={`px-3.5 py-1.5 rounded-full display font-bold text-base tracking-wider transition-all ${
                season === y
                  ? "bg-f1red text-white shadow-glow"
                  : "bg-white/[.04] border border-white/10 text-ink-300 hover:text-white hover:border-white/25"
              }`}
            >
              {y}
            </button>
          ))}
        </div>
        <div className="relative w-full sm:w-72">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
          <input
            type="text"
            placeholder="Search circuits…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full bg-white/[.04] border border-white/10 rounded-full pl-9 pr-4 py-2 text-sm text-white placeholder-ink-500 focus:outline-none focus:border-f1red/60 focus:bg-white/[.06] transition-colors"
          />
        </div>
      </div>

      <p className="text-xs text-ink-500 -mt-3">
        <span className="text-ink-300 font-semibold">{seasonRaces.length}</span> races in {season}
        {" · "}<span className="text-emerald-400 font-semibold">{cachedInSeason}</span> cached for instant replay
      </p>

      {/* Race grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.map((race) => (
          <button
            key={race.race_id}
            onClick={() => onSelect(race)}
            className="card card-hover group relative overflow-hidden text-left p-4"
          >
            <span className="absolute -right-2 -top-4 display font-extrabold text-[84px] leading-none text-white/[.04] group-hover:text-f1red/15 transition-colors select-none">
              {String(race.round_number).padStart(2, "0")}
            </span>
            <div className="relative">
              <p className="display font-semibold text-[11px] tracking-[.25em] text-f1red uppercase">
                Round {race.round_number}
              </p>
              <p className="display font-bold text-xl leading-tight mt-0.5">{race.event_name}</p>
              <p className="text-xs text-ink-500 mt-1 flex items-center gap-1"><MapPin size={11} />{race.circuit}</p>
              <div className="flex items-center gap-2 mt-3 flex-wrap">
                {race.total_laps > 0 && (
                  <span className="chip"><Clock size={10} />{race.total_laps} laps</span>
                )}
                {race.event_date && <span className="chip mono">{race.event_date}</span>}
                {race.cached && (
                  <span className="chip !text-emerald-300 !border-emerald-500/30 !bg-emerald-500/10">cached</span>
                )}
              </div>
            </div>
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="text-ink-500 text-sm col-span-full py-10 text-center">No races match “{searchQuery}”.</p>
        )}
      </div>
    </div>
  );
}
