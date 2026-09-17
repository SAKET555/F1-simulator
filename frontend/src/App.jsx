import { useState } from "react";
import "./index.css";

import { useRaceSocket }       from "./hooks/useRaceSocket";
import RaceSelector            from "./components/RaceSelector";
import Leaderboard             from "./components/Leaderboard";
import WinProbabilityChart     from "./components/WinProbabilityChart";
import CounterfactualPanel     from "./components/CounterfactualPanel";
import SpeedControl            from "./components/SpeedControl";
import { Radio }               from "lucide-react";

export default function App() {
  const [selectedRace, setSelectedRace] = useState(null);   // historical race object
  const [isLive,       setIsLive]       = useState(false);  // live OpenF1 mode
  const [speed,        setSpeedState]   = useState(2);
  const [paused,       setPaused]       = useState(false);

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
    setPaused(false);
  }

  function handleLive(session) {
    setSelectedRace(null);
    setIsLive(true);
  }

  const cars      = raceState?.cars       ?? [];
  const lap       = raceState?.lap        ?? null;
  const totalLaps = raceState?.total_laps ?? selectedRace?.total_laps ?? 70;
  const sessionName = raceState?.session_name
    ?? (isLive ? "Live Session" : selectedRace?.event_name ?? "");

  const inDashboard = selectedRace !== null || isLive;

  return (
    <div className="min-h-screen bg-pitwall text-white flex flex-col">

      {/* ── Header ──────────────────────────────────────────────────── */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-panel/80 backdrop-blur sticky top-0 z-10">
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-f1red font-black text-xl tracking-tight flex-shrink-0">SAK</span>
          <span className="text-white font-semibold text-sm tracking-widest flex-shrink-0">RACING SIM</span>
          {inDashboard && (
            <>
              <span className="text-gray-600 mx-1">/</span>
              <span className="text-gray-400 text-sm truncate">{sessionName}</span>
              {isLive && (
                <span className="flex items-center gap-1 text-[11px] font-bold text-red-400 bg-red-500/10 px-2 py-0.5 rounded-full flex-shrink-0">
                  <Radio size={10} className="animate-pulse" /> LIVE
                </span>
              )}
            </>
          )}
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
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
            <button
              onClick={handleBack}
              className="text-xs text-gray-500 hover:text-white underline transition-colors"
            >
              Back
            </button>
          )}
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────── */}
      <main className="flex-1 p-4 md:p-6">
        {!inDashboard ? (
          <RaceSelector onSelect={setSelectedRace} onLive={handleLive} />
        ) : (
          <>
            {/* Info message (live: no race active) */}
            {infoMsg && (
              <div className="mb-4 bg-blue-900/20 border border-blue-700/30 rounded-xl px-6 py-3 text-sm text-blue-300">
                {infoMsg}
              </div>
            )}

            {/* Winner banner */}
            {status === "finished" && winner && (
              <div className="mb-4 bg-f1red/10 border border-f1red rounded-xl px-6 py-3 flex items-center gap-3">
                <span className="text-2xl">&#127942;</span>
                <div>
                  <p className="text-f1red font-bold text-sm uppercase tracking-widest">
                    {isLive ? "Race Finished" : "Race Finished"}
                  </p>
                  <p className="text-white font-black text-lg">{winner} wins!</p>
                </div>
              </div>
            )}

            {/* Dashboard grid */}
            <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr_320px] gap-4">

              {/* Col 1: Leaderboard */}
              <div className="bg-panel border border-border rounded-xl p-4" style={{ minHeight: 480 }}>
                <Leaderboard cars={cars} lap={lap} totalLaps={totalLaps} />
              </div>

              {/* Col 2: Chart + telemetry */}
              <div className="bg-panel border border-border rounded-xl p-4 flex flex-col gap-4">
                <WinProbabilityChart predictions={predictions} />

                {/* Lap progress bar */}
                {lap != null && (
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>Lap progress</span>
                      <span>{lap} / {totalLaps}</span>
                    </div>
                    <div className="h-2 bg-border rounded-full overflow-hidden">
                      <div
                        className="h-full bg-f1red rounded-full transition-all duration-500"
                        style={{ width: `${Math.min((lap / totalLaps) * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                )}

                {/* Top-3 snapshot */}
                {cars.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 mb-2">Top 3 snapshot</p>
                    <div className="grid grid-cols-3 gap-2">
                      {cars.slice(0, 3).map((c, idx) => (
                        <div
                          key={c.car_id}
                          className="bg-pitwall border border-border rounded-lg p-2 text-center"
                        >
                          <p className={`text-xs font-bold mb-0.5 ${
                            idx === 0 ? "text-f1red" : idx === 1 ? "text-gray-300" : "text-yellow-600"
                          }`}>P{c.position}</p>
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

              {/* Col 3: Counterfactual (disabled in live mode — data loads after race) */}
              <div className="bg-panel border border-border rounded-xl p-4">
                {isLive ? (
                  <div className="flex flex-col gap-3">
                    <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest">
                      Strategy Sim
                    </h2>
                    <p className="text-xs text-gray-600 leading-relaxed">
                      Counterfactual simulation is available for historical replays.
                      The live stream feeds real OpenF1 timing data directly.
                    </p>
                    <div className="flex items-center gap-2 mt-2">
                      <Radio size={12} className="text-red-400 animate-pulse" />
                      <span className="text-xs text-red-400 font-semibold">Receiving live data</span>
                    </div>
                  </div>
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
          </>
        )}
      </main>

      <footer className="text-center text-xs text-gray-700 py-2 border-t border-border">
        SAK Racing Sim &middot; FastF1 + OpenF1 + Monte Carlo &middot; {new Date().getFullYear()}
      </footer>
    </div>
  );
}
