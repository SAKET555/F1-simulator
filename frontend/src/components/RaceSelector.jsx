import { useEffect, useState } from "react";
import { API_BASE, WS_BASE } from "../lib/constants";
import { Clock, Radio } from "lucide-react";

export default function RaceSelector({ onSelect, onLive }) {
  const [races,        setRaces]        = useState([]);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState(null);
  const [season,       setSeason]       = useState("LIVE");
  const [liveStatus,   setLiveStatus]   = useState(null);   // null | { live, session }
  const [liveChecking, setLiveChecking] = useState(false);
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

  // Check live session when LIVE tab is selected
  useEffect(() => {
    if (season !== "LIVE") return;
    setLiveChecking(true);
    fetch(`${API_BASE}/live/session`)
      .then((r) => r.json())
      .then(setLiveStatus)
      .catch(() => setLiveStatus({ live: false, session: null }))
      .finally(() => setLiveChecking(false));
  }, [season]);

  if (loading) return <p className="text-gray-500 text-sm p-6">Loading race library...</p>;
  if (error)   return <p className="text-red-400 text-sm p-6">{error}</p>;

  const years = [...new Set(races.map((r) => r.year))].sort((a, b) => b - a);
  const seasonRaces = season !== "LIVE" ? races.filter((r) => r.year === Number(season)) : [];
  const filtered = seasonRaces.filter(r =>
    !searchQuery ||
    r.circuit?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    r.event_name?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex flex-col gap-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-black text-white tracking-tight">
          <span className="text-f1red">SAK</span> RACING SIM
        </h1>
        <p className="text-xs text-gray-500 mt-1">
          Select a race to replay, or go live during an active race weekend
        </p>
      </div>

      {/* Season / Live tabs */}
      <div className="flex gap-1 flex-wrap">
        {/* Live tab */}
        <button
          onClick={() => setSeason("LIVE")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-sm font-bold transition-colors ${
            season === "LIVE"
              ? "bg-f1red text-white"
              : "bg-panel border border-border text-gray-400 hover:text-white"
          }`}
        >
          <Radio size={12} className={season === "LIVE" ? "animate-pulse" : ""} />
          LIVE
        </button>

        {/* Year tabs */}
        {years.map((y) => (
          <button
            key={y}
            onClick={() => setSeason(y)}
            className={`px-3 py-1.5 rounded text-sm font-bold transition-colors ${
              season === y
                ? "bg-f1red text-white"
                : "bg-panel border border-border text-gray-400 hover:text-white"
            }`}
          >
            {y}
          </button>
        ))}
      </div>

      {/* LIVE panel */}
      {season === "LIVE" && (
        <div className="bg-panel border border-border rounded-xl p-6">
          {liveChecking ? (
            <p className="text-gray-500 text-sm">Checking for live session...</p>
          ) : liveStatus?.live ? (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse" />
                <span className="text-white font-bold text-lg">Race in progress</span>
              </div>
              <div className="text-sm text-gray-400">
                <p className="font-semibold text-white">
                  {liveStatus.session?.location} Grand Prix
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  {liveStatus.session?.year} &middot; Session key: {liveStatus.session?.session_key}
                </p>
              </div>
              <button
                onClick={() => onLive(liveStatus.session)}
                className="w-fit px-6 py-2 bg-f1red hover:bg-red-700 rounded text-white font-bold text-sm transition-colors flex items-center gap-2"
              >
                <Radio size={14} />
                Connect to Live Timing
              </button>
              <p className="text-[11px] text-gray-600">
                Powered by OpenF1 API (openf1.org) — 100% free, no sign-up required
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-3">
                <span className="w-3 h-3 rounded-full bg-gray-600" />
                <span className="text-gray-400 font-semibold">No live race right now</span>
              </div>
              <p className="text-xs text-gray-600 leading-relaxed">
                Live timing via OpenF1 is active during race weekends only.<br />
                Select a season below to replay historical races at 2×/5×/10× speed.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Historical race grid */}
      {season !== "LIVE" && (
        <>
        <input
          type="text"
          placeholder="Search circuits…"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          className="w-full bg-pitwall border border-border rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((race) => (
            <button
              key={race.race_id}
              onClick={() => onSelect(race)}
              className="flex items-start gap-3 bg-panel border border-border hover:border-f1red/60 hover:bg-panel/80 rounded-xl p-4 text-left transition-all group"
            >
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-pitwall border border-border flex items-center justify-center text-xs font-black text-gray-400 group-hover:border-f1red/40">
                {race.round_number}
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-white text-sm leading-tight">
                  {race.event_name}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">{race.circuit}</p>
                <div className="flex items-center gap-2 mt-1.5">
                  {race.total_laps > 0 && (
                    <span className="text-[10px] text-gray-600 flex items-center gap-1">
                      <Clock size={9} />{race.total_laps} laps
                    </span>
                  )}
                  {race.event_date && (
                    <span className="text-[10px] text-gray-600">{race.event_date}</span>
                  )}
                  {race.cached && (
                    <span className="text-[10px] text-green-500 bg-green-500/10 px-1.5 rounded">
                      cached
                    </span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
        </>
      )}
    </div>
  );
}
