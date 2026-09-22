import { useState } from "react";
import "./index.css";

import { useRaceSocket }                    from "./hooks/useRaceSocket";
import { useKeyboardShortcuts }             from "./hooks/useKeyboardShortcuts";
import { useShareableUrl, copyShareLink }   from "./hooks/useShareableUrl";

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
import TrackMap            from "./components/TrackMap";
import UndercutCalc        from "./components/UndercutCalc";
import StintAnalysis       from "./components/StintAnalysis";
import QualifyingGrid      from "./components/QualifyingGrid";
import ChampionshipPanel   from "./components/ChampionshipPanel";
import TeamRadio           from "./components/TeamRadio";
import { Radio, Share2 }   from "lucide-react";

const TABS = ["Overview", "Charts", "Telemetry", "Strategy", "Qualifying"];

export default function App() {
  const [selectedRace, setSelectedRace] = useState(null);
  const [isLive,       setIsLive]       = useState(false);
  const [liveSession,  setLiveSession]  = useState(null);
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
    isLive,
  );

  function handleSpeedChange(s) { setSpeedState(s); setSpeedRemote(s); }
  function handlePause()        { setPaused(true);  pause();  }
  function handleResume()       { setPaused(false); resume(); }

  function handleBack() {
    setSelectedRace(null);
    setIsLive(false);
    setLiveSession(null);
    setPaused(false);
    setActiveTab("Overview");
  }

  function handleLive(session) {
    setSelectedRace(null);
    setIsLive(true);
    setLiveSession(session);
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
    enabled: !!(selectedRace || isLive),
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
  const sessionName = raceState?.session_name
    ?? (isLive ? "Live Session" : selectedRace?.event_name ?? "");
  const inDashboard = selectedRace !== null || isLive;
  const raceYear    = selectedRace?.year ?? new Date().getFullYear();

  return (
    <div className="min-h-screen bg-pitwall text-white flex flex-col">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-panel/80 backdrop-blur sticky top-0 z-20">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-f1red font-black text-xl tracking-tight flex-shrink-0">SAK</span>
          <span className="text-white font-semibold text-sm tracking-widest flex-shrink-0">RACING SIM</span>
          {inDashboard && (
            <>
              <span className="text-gray-600 mx-1 hidden sm:inline">/</span>
              <span className="text-gray-400 text-sm truncate hidden sm:inline">{sessionName}</span>
              {isLive && (
                <span className="flex items-center gap-1 text-[11px] font-bold text-red-400 bg-red-500/10 px-2 py-0.5 rounded-full flex-shrink-0">
                  <Radio size={10} className="animate-pulse" /> LIVE
                </span>
              )}
            </>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {inDashboard && !isLive && (
            <SpeedControl
              speed={speed}
              onSpeedChange={handleSpeedChange}
              paused={paused}
              onPause={handlePause}
              onResume={handleResume}
              status={status}
            />
          )}
          {isLive && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
              status === "live" ? "bg-green-600/20 text-green-400 animate-pulse" :
              status === "error" ? "bg-red-600/20 text-red-400" :
              "bg-gray-600/20 text-gray-400"
            }`}>
              {status.toUpperCase()}
            </span>
          )}
          {inDashboard && (
            <button onClick={handleShare}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-white transition-colors px-2 py-1 rounded border border-border hover:border-gray-500">
              <Share2 size={11} />
              <span>{shared ? "Copied!" : "Share"}</span>
            </button>
          )}
          {inDashboard && (
            <button onClick={handleBack}
              className="text-xs text-gray-500 hover:text-white underline transition-colors">
              Back
            </button>
          )}
        </div>
      </header>

      {/* ── Tab bar ──────────────────────────────────────────────────────── */}
      {inDashboard && (
        <div className="flex border-b border-border bg-panel/60 sticky top-[49px] z-10 overflow-x-auto">
          {TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-xs font-semibold whitespace-nowrap transition-colors border-b-2 ${
                activeTab === tab
                  ? "border-f1red text-white"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      )}

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <main className="flex-1 p-4 md:p-5">
        {!inDashboard ? (
          <RaceSelector onSelect={setSelectedRace} onLive={handleLive} />
        ) : (
          <>
            {infoMsg && (
              <div className="mb-3 bg-blue-900/20 border border-blue-700/30 rounded-xl px-4 py-2.5 text-sm text-blue-300">
                {infoMsg}
              </div>
            )}
            {status === "finished" && winner && (
              <div className="mb-3 bg-f1red/10 border border-f1red rounded-xl px-4 py-2.5 flex items-center gap-3">
                <span className="text-2xl">&#127942;</span>
                <div>
                  <p className="text-f1red font-bold text-xs uppercase tracking-widest">Race Finished</p>
                  <p className="text-white font-black text-lg">{winner} wins!</p>
                </div>
              </div>
            )}

            {/* Lap progress + weather */}
            <div className="mb-3 space-y-2">
              {lap != null && (
                <div>
                  <div className="flex justify-between text-xs text-gray-500 mb-1">
                    <span>Lap progress — Space=pause · 2/5/0=speed</span>
                    <span>{lap} / {totalLaps}</span>
                  </div>
                  <div className="h-1.5 bg-border rounded-full overflow-hidden">
                    <div
                      className="h-full bg-f1red rounded-full transition-all duration-500"
                      style={{ width: `${Math.min((lap / totalLaps) * 100, 100)}%` }}
                    />
                  </div>
                </div>
              )}
              {selectedRace && <WeatherWidget raceId={selectedRace.race_id} currentLap={lap ?? 1} />}
            </div>

            {/* ── OVERVIEW TAB ─────────────────────────────────────────── */}
            {activeTab === "Overview" && (
              <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr_300px] gap-4">
                <div className="bg-panel border border-border rounded-xl p-4" style={{ minHeight: 460 }}>
                  <Leaderboard cars={cars} lap={lap} totalLaps={totalLaps} />
                </div>

                <div className="bg-panel border border-border rounded-xl p-4 flex flex-col gap-4">
                  <WinProbabilityChart predictions={predictions} />
                  {cars.length > 0 && (
                    <div>
                      <p className="text-xs text-gray-500 mb-2">Top 3 snapshot</p>
                      <div className="grid grid-cols-3 gap-2">
                        {cars.slice(0, 3).map((c, idx) => (
                          <div key={c.car_id} className="bg-pitwall border border-border rounded-lg p-2 text-center">
                            <p className={`text-xs font-bold mb-0.5 ${idx === 0 ? "text-f1red" : idx === 1 ? "text-gray-300" : "text-yellow-600"}`}>
                              P{c.position}
                            </p>
                            <p className="text-white font-black text-sm">{c.driver_code}</p>
                            <p className="text-gray-600 text-[10px] truncate">{c.team}</p>
                            <p className="text-gray-400 text-[10px] mt-1">
                              {c.lap_time_s ? `${c.lap_time_s.toFixed(3)}s` : "—"}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                <div className="bg-panel border border-border rounded-xl p-4">
                  {isLive ? (
                    <TeamRadio isLive={isLive} sessionKey={liveSession?.session_key} />
                  ) : (
                    <CounterfactualPanel
                      raceId={selectedRace?.race_id}
                      cars={cars}
                      totalLaps={totalLaps}
                      currentLap={lap ?? 1}
                    />
                  )}
                </div>
              </div>
            )}

            {/* ── CHARTS TAB ───────────────────────────────────────────── */}
            {activeTab === "Charts" && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="bg-panel border border-border rounded-xl p-4">
                  {selectedRace
                    ? <GapChart raceId={selectedRace.race_id} />
                    : <p className="text-gray-600 text-sm text-center mt-8">Historical races only</p>}
                </div>
                <div className="bg-panel border border-border rounded-xl p-4">
                  <LapDeltaChart cars={cars} />
                </div>
              </div>
            )}

            {/* ── TELEMETRY TAB ────────────────────────────────────────── */}
            {activeTab === "Telemetry" && (
              <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-4">
                <div className="space-y-4">
                  <div className="bg-panel border border-border rounded-xl p-4">
                    {selectedRace
                      ? <TelemetryPanel raceId={selectedRace.race_id} cars={cars} />
                      : <p className="text-gray-600 text-sm">Historical races only</p>}
                  </div>
                  <div className="bg-panel border border-border rounded-xl p-4">
                    {selectedRace
                      ? <SectorHeatmap raceId={selectedRace.race_id} cars={cars} />
                      : <p className="text-gray-600 text-sm">Historical races only</p>}
                  </div>
                </div>
                <div className="bg-panel border border-border rounded-xl p-4">
                  {selectedRace
                    ? <TrackMap raceId={selectedRace.race_id} cars={cars} currentLap={lap ?? 1} />
                    : <p className="text-gray-600 text-sm">Historical races only</p>}
                </div>
              </div>
            )}

            {/* ── STRATEGY TAB ─────────────────────────────────────────── */}
            {activeTab === "Strategy" && (
              <div className="grid grid-cols-1 xl:grid-cols-[360px_1fr] gap-4">
                <div className="space-y-4">
                  <div className="bg-panel border border-border rounded-xl p-4">
                    <UndercutCalc
                      raceId={selectedRace?.race_id}
                      cars={cars}
                      currentLap={lap ?? 1}
                      totalLaps={totalLaps}
                    />
                  </div>
                  <div className="bg-panel border border-border rounded-xl p-4">
                    <CounterfactualPanel
                      raceId={selectedRace?.race_id}
                      cars={cars}
                      totalLaps={totalLaps}
                      currentLap={lap ?? 1}
                    />
                  </div>
                </div>
                <div className="bg-panel border border-border rounded-xl p-4">
                  <StintAnalysis raceId={selectedRace?.race_id} totalLaps={totalLaps} />
                </div>
              </div>
            )}

            {/* ── QUALIFYING TAB ───────────────────────────────────────── */}
            {activeTab === "Qualifying" && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="bg-panel border border-border rounded-xl p-4">
                  <QualifyingGrid raceId={selectedRace?.race_id} />
                </div>
                <div className="bg-panel border border-border rounded-xl p-4">
                  <ChampionshipPanel year={raceYear} />
                </div>
              </div>
            )}
          </>
        )}
      </main>

      <footer className="text-center text-xs text-gray-700 py-2 border-t border-border">
        SAK Racing Sim · FastF1 + OpenF1 + Monte Carlo · {new Date().getFullYear()} · Space=pause · 2/5/0=speed
      </footer>
    </div>
  );
}
