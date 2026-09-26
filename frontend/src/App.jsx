import { useState } from "react";
import "./index.css";

import { useRaceSocket }                    from "./hooks/useRaceSocket";
import { useKeyboardShortcuts }             from "./hooks/useKeyboardShortcuts";
import { useShareableUrl, copyShareLink }   from "./hooks/useShareableUrl";
import { getTeamColor }                     from "./lib/constants";

import RaceSelector        from "./components/RaceSelector";
import Leaderboard         from "./components/Leaderboard";
import WinProbabilityChart from "./components/WinProbabilityChart";
import CounterfactualPanel from "./components/CounterfactualPanel";
import SpeedControl        from "./components/SpeedControl";
import WeatherWidget       from "./components/WeatherWidget";
import GapChart            from "./components/GapChart";
import LapDeltaChart       from "./components/LapDeltaChart";
import TelemetryPanel      from "./components/TelemetryPanel";
import SectorHeatmap       from "./components/SectorHeatmap";
import CircuitImage        from "./components/CircuitImage";
import TrajectoryMap       from "./components/TrajectoryMap";
import AnalyticsPanel      from "./components/AnalyticsPanel";
import InsightsPanel       from "./components/InsightsPanel";
import UndercutCalc        from "./components/UndercutCalc";
import StintAnalysis       from "./components/StintAnalysis";
import QualifyingGrid      from "./components/QualifyingGrid";
import ChampionshipPanel   from "./components/ChampionshipPanel";
import {
  Share2, ArrowLeft, LayoutDashboard, LineChart, BarChart3, Sparkles, Activity, Route, Flag,
  CalendarDays, MapPin, Trophy, Timer,
} from "lucide-react";

const TABS = ["Overview", "Charts", "Analytics", "Insights", "Telemetry", "Strategy", "Qualifying"];
const TAB_ICONS = {
  Overview: LayoutDashboard, Charts: LineChart, Analytics: BarChart3, Insights: Sparkles,
  Telemetry: Activity, Strategy: Route, Qualifying: Flag,
};

export default function App() {
  const [selectedRace, setSelectedRace] = useState(null);
  const [speed,        setSpeedState]   = useState(2);
  const [paused,       setPaused]       = useState(false);
  const [activeTab,    setActiveTab]    = useState("Overview");
  const [shared,       setShared]       = useState(false);

  const {
    raceState,
    predictions,
    status,
    winner,
    infoMsg,
    pause,
    resume,
    setSpeed: setSpeedRemote,
  } = useRaceSocket(
    selectedRace?.race_id ?? null,
    speed,
  );

  function handleSpeedChange(s) { setSpeedState(s); setSpeedRemote(s); }
  function handlePause()        { setPaused(true);  pause();  }
  function handleResume()       { setPaused(false); resume(); }

  function handleBack() {
    setSelectedRace(null);
    setPaused(false);
    setActiveTab("Overview");
  }

  function handleShare() {
    copyShareLink();
    setShared(true);
    setTimeout(() => setShared(false), 2000);
  }

  useKeyboardShortcuts({
    onPause: handlePause,
    onResume: handleResume,
    onSpeedChange: handleSpeedChange,
    paused,
    enabled: selectedRace !== null,
  });

  useShareableUrl({
    raceId: selectedRace?.race_id ?? null,
    lap: raceState?.lap ?? null,
    onRestore: ({ raceId }) => {
      fetch(`http://localhost:8000/api/races/${raceId}`)
        .then(r => r.ok ? r.json() : null)
        .then(meta => { if (meta) setSelectedRace(meta); })
        .catch(() => {});
    },
  });

  const cars        = raceState?.cars       ?? [];
  const lap         = raceState?.lap        ?? null;
  const totalLaps   = raceState?.total_laps ?? selectedRace?.total_laps ?? 70;
  const sessionName = raceState?.session_name ?? selectedRace?.event_name ?? "";
  const inDashboard = selectedRace !== null;
  const raceYear    = selectedRace?.year ?? new Date().getFullYear();
  const pct         = lap != null ? Math.min((lap / totalLaps) * 100, 100) : 0;

  return (
    <div className="min-h-screen text-white flex flex-col">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-white/5 bg-[#0b0d13]/80 backdrop-blur-xl">
        <div className="flex items-center justify-between gap-3 px-4 md:px-6 h-14">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={inDashboard ? handleBack : undefined}
              className={`flex items-center gap-2 flex-shrink-0 ${inDashboard ? "cursor-pointer" : "cursor-default"}`}
              title={inDashboard ? "Back to all races" : undefined}
            >
              <span className="relative inline-flex items-center justify-center h-7 px-2.5 -skew-x-12 bg-f1red shadow-glow">
                <span className="skew-x-12 display font-extrabold text-lg leading-none tracking-wider">SAK</span>
              </span>
              <span className="display font-bold text-lg tracking-[.28em] text-white/90 hidden sm:inline">RACING SIM</span>
            </button>
            {inDashboard && (
              <div className="hidden md:flex items-center gap-2 min-w-0 pl-3 ml-1 border-l border-white/10">
                <span className="text-sm text-ink-300 truncate">{sessionName}</span>
                <span className="chip">{raceYear}</span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {inDashboard && (
              <SpeedControl
                speed={speed}
                onSpeedChange={handleSpeedChange}
                paused={paused}
                onPause={handlePause}
                onResume={handleResume}
                status={status}
              />
            )}
            {inDashboard && (
              <button
                onClick={handleShare}
                className="flex items-center gap-1.5 text-xs text-ink-300 hover:text-white transition-colors px-2.5 py-1.5 rounded-lg border border-white/10 hover:border-white/25 bg-white/[.03]"
              >
                <Share2 size={12} />
                <span className="hidden sm:inline">{shared ? "Copied!" : "Share"}</span>
              </button>
            )}
            {inDashboard && (
              <button
                onClick={handleBack}
                className="flex items-center gap-1.5 text-xs text-ink-300 hover:text-white transition-colors px-2.5 py-1.5 rounded-lg border border-white/10 hover:border-white/25 bg-white/[.03]"
              >
                <ArrowLeft size={12} />
                <span className="hidden sm:inline">Races</span>
              </button>
            )}
          </div>
        </div>

        {/* ── Tab bar ─────────────────────────────────────────────────── */}
        {inDashboard && (
          <nav className="flex px-2 md:px-5 overflow-x-auto border-t border-white/5">
            {TABS.map(tab => {
              const Icon = TAB_ICONS[tab];
              const active = activeTab === tab;
              return (
                <button
                  key={tab}
                  data-active={active}
                  onClick={() => setActiveTab(tab)}
                  className={`tab flex items-center gap-1.5 px-3.5 py-2.5 text-[13px] font-semibold whitespace-nowrap transition-colors ${
                    active ? "text-white" : "text-ink-500 hover:text-ink-300"
                  }`}
                >
                  <Icon size={14} className={active ? "text-f1red" : ""} />
                  {tab}
                </button>
              );
            })}
          </nav>
        )}
      </header>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <main className="flex-1 p-4 md:p-6 max-w-[1800px] w-full mx-auto">
        {!inDashboard ? (
          <RaceSelector onSelect={setSelectedRace} />
        ) : (
          <div key={activeTab} className="animate-fadeUp">
            {infoMsg && (
              <div className="mb-4 bg-sky-500/10 border border-sky-500/25 rounded-xl px-4 py-2.5 text-sm text-sky-300">
                {infoMsg}
              </div>
            )}
            {status === "finished" && winner && (
              <div className="mb-4 rounded-2xl border border-f1red/50 bg-gradient-to-r from-f1red/20 via-f1red/5 to-transparent px-5 py-3.5 flex items-center gap-4 shadow-glow">
                <Trophy className="text-yellow-400" size={30} />
                <div>
                  <p className="text-f1red display font-bold text-xs uppercase tracking-[.25em]">Race finished</p>
                  <p className="display font-extrabold text-2xl leading-tight">{winner} wins!</p>
                </div>
              </div>
            )}

            {/* Race hero + lap progress + weather */}
            {activeTab === "Overview" && (
              <div className="card p-4 md:p-5 mb-4 relative overflow-hidden">
                <div className="absolute -right-10 -top-16 w-72 h-72 rounded-full bg-f1red/10 blur-3xl pointer-events-none" />
                <div className="relative flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
                  <div className="min-w-0">
                    <p className="display font-semibold text-xs tracking-[.3em] text-f1red uppercase">
                      {raceYear} · Round {selectedRace.round_number}
                    </p>
                    <h1 className="display font-extrabold text-3xl md:text-4xl leading-none mt-1 truncate">
                      {selectedRace.event_name}
                    </h1>
                    <div className="flex flex-wrap gap-2 mt-2.5">
                      {selectedRace.circuit && <span className="chip"><MapPin size={11} />{selectedRace.circuit}</span>}
                      {selectedRace.event_date && <span className="chip"><CalendarDays size={11} />{selectedRace.event_date}</span>}
                      <span className="chip"><Timer size={11} />{totalLaps} laps</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] uppercase tracking-[.25em] text-ink-500">Lap</p>
                    <p className="display font-extrabold text-5xl leading-none mono">
                      {lap ?? "–"}<span className="text-ink-500 text-2xl"> / {totalLaps}</span>
                    </p>
                  </div>
                </div>

                <div className="relative mt-4">
                  <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-f1red to-orange-500 shadow-[0_0_14px_rgba(225,6,0,.7)] transition-all duration-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px] text-ink-500 mt-1.5">
                    <span>Space = pause · 2 / 5 / 0 = speed</span>
                    <span className="mono">{pct.toFixed(0)}%</span>
                  </div>
                </div>
                <div className="relative mt-3">
                  <WeatherWidget raceId={selectedRace.race_id} currentLap={lap ?? 1} />
                </div>
              </div>
            )}

            {/* ── OVERVIEW TAB ─────────────────────────────────────────── */}
            {activeTab === "Overview" && (
              <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr_320px] gap-4">
                <div className="card p-4" style={{ minHeight: 460 }}>
                  <Leaderboard cars={cars} lap={lap} totalLaps={totalLaps} />
                </div>

                <div className="card p-4 flex flex-col gap-5">
                  <WinProbabilityChart predictions={predictions} />
                  {cars.length > 0 && (
                    <div>
                      <h3 className="mb-3">Top 3 snapshot</h3>
                      <div className="grid grid-cols-3 gap-3">
                        {cars.slice(0, 3).map((c, idx) => {
                          const col = getTeamColor(c.team);
                          return (
                            <div
                              key={c.car_id}
                              className="relative overflow-hidden rounded-xl border border-white/10 bg-white/[.03] p-3 text-center"
                              style={{ boxShadow: `inset 0 2px 0 ${col}` }}
                            >
                              <div
                                className="absolute inset-x-0 top-0 h-16 opacity-25 pointer-events-none"
                                style={{ background: `linear-gradient(180deg, ${col}, transparent)` }}
                              />
                              <p className={`relative display font-extrabold text-sm tracking-widest ${
                                idx === 0 ? "text-f1red" : idx === 1 ? "text-ink-300" : "text-amber-500"
                              }`}>
                                P{c.position}
                              </p>
                              <p className="relative display font-extrabold text-2xl leading-tight">{c.driver_code}</p>
                              <p className="relative text-ink-500 text-[10px] truncate">{c.team}</p>
                              <p className="relative mono text-ink-300 text-xs mt-1.5">
                                {c.lap_time_s ? `${c.lap_time_s.toFixed(3)}s` : "—"}
                              </p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>

                <div className="card p-4">
                  <CounterfactualPanel
                    raceId={selectedRace?.race_id}
                    cars={cars}
                    totalLaps={totalLaps}
                    currentLap={lap ?? 1}
                  />
                </div>
              </div>
            )}

            {/* ── CHARTS TAB ───────────────────────────────────────────── */}
            {activeTab === "Charts" && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="card p-4">
                  <GapChart raceId={selectedRace.race_id} />
                </div>
                <div className="card p-4">
                  <LapDeltaChart cars={cars} />
                </div>
              </div>
            )}

            {/* ── ANALYTICS TAB ────────────────────────────────────────── */}
            {activeTab === "Analytics" && (
              <AnalyticsPanel raceId={selectedRace?.race_id} />
            )}

            {/* ── INSIGHTS TAB ─────────────────────────────────────────── */}
            {activeTab === "Insights" && (
              <InsightsPanel raceId={selectedRace?.race_id} year={selectedRace?.year} />
            )}

            {/* ── TELEMETRY TAB ────────────────────────────────────────── */}
            {activeTab === "Telemetry" && (
              <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-4">
                <div className="space-y-4">
                  <div className="card p-4">
                    <TelemetryPanel raceId={selectedRace.race_id} cars={cars} />
                  </div>
                  <div className="card p-4">
                    <SectorHeatmap raceId={selectedRace.race_id} cars={cars} />
                  </div>
                  <div className="card p-4">
                    <TrajectoryMap raceId={selectedRace.race_id} cars={cars} />
                  </div>
                </div>
                <div className="card p-4">
                  <CircuitImage raceId={selectedRace.race_id} />
                </div>
              </div>
            )}

            {/* ── STRATEGY TAB ─────────────────────────────────────────── */}
            {activeTab === "Strategy" && (
              <div className="grid grid-cols-1 xl:grid-cols-[360px_1fr] gap-4">
                <div className="space-y-4">
                  <div className="card p-4">
                    <UndercutCalc
                      raceId={selectedRace?.race_id}
                      cars={cars}
                      currentLap={lap ?? 1}
                      totalLaps={totalLaps}
                    />
                  </div>
                  <div className="card p-4">
                    <CounterfactualPanel
                      raceId={selectedRace?.race_id}
                      cars={cars}
                      totalLaps={totalLaps}
                      currentLap={lap ?? 1}
                    />
                  </div>
                </div>
                <div className="card p-4">
                  <StintAnalysis raceId={selectedRace?.race_id} totalLaps={totalLaps} />
                </div>
              </div>
            )}

            {/* ── QUALIFYING TAB ───────────────────────────────────────── */}
            {activeTab === "Qualifying" && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="card p-4">
                  <QualifyingGrid raceId={selectedRace?.race_id} />
                </div>
                <div className="card p-4">
                  <ChampionshipPanel year={raceYear} raceId={selectedRace?.race_id} />
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="text-center text-[11px] text-ink-700 py-3 border-t border-white/5">
        SAK Racing Sim · FastF1 + Monte Carlo · {new Date().getFullYear()}
      </footer>
    </div>
  );
}
