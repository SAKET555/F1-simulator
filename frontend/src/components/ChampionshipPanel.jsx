import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

export default function ChampionshipPanel({ year, raceId }) {
  const [tab, setTab] = useState("standings");
  const [pointsTab, setPointsTab] = useState("drivers");
  const [drivers, setDrivers] = useState([]);
  const [constructors, setConstructors] = useState([]);
  const [racePoints, setRacePoints] = useState(null);   // points_this_race, from /points
  const [eventName, setEventName] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (raceId) {
      // One request gets this race's points *and* the standings immediately
      // after it — more useful mid-replay than always showing the season's
      // final result regardless of which race is on screen.
      setLoading(true);
      fetch(`${API_BASE}/races/${raceId}/points`)
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (d) {
            setDrivers(d.driver_standings_after ?? []);
            setConstructors(d.constructor_standings_after ?? []);
            setRacePoints(d.points_this_race ?? []);
            setEventName(d.event_name ?? null);
          } else {
            setDrivers([]); setConstructors([]); setRacePoints([]);
          }
          setLoading(false);
        })
        .catch(() => { setDrivers([]); setConstructors([]); setRacePoints([]); setLoading(false); });
      return;
    }
    if (!year) return;
    setRacePoints(null);
    setEventName(null);
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/championship/${year}/drivers`).then(r => r.ok ? r.json() : []).catch(() => []),
      fetch(`${API_BASE}/championship/${year}/constructors`).then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([d, c]) => {
      setDrivers(Array.isArray(d) ? d : []);
      setConstructors(Array.isArray(c) ? c : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [year, raceId]);

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex-1 truncate">
          {year} Championship{eventName ? ` — after ${eventName}` : ""}
        </h3>
        {racePoints && racePoints.length > 0 && (
          <div className="flex rounded overflow-hidden border border-border text-xs flex-shrink-0">
            {[["standings", "Standings"], ["thisrace", "This Race"]].map(([t, label]) => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-2 py-0.5 transition whitespace-nowrap ${tab === t ? "bg-f1red text-white" : "text-gray-400 hover:text-white"}`}>
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-32 text-gray-600 text-xs text-center px-4 leading-relaxed">
          Loading standings… first load for a season can take up to a
          minute (it's built from every race that season); it's instant
          after that.
        </div>
      ) : tab === "thisrace" && racePoints ? (
        <div className="space-y-1 overflow-auto max-h-72">
          {racePoints.map(p => (
            <div key={p.driver_code} className={`flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5 ${p.retired ? "opacity-50" : ""}`}>
              <span className="w-5 text-gray-500 text-xs">{p.retired ? "—" : p.position}</span>
              <span className="w-8 font-bold text-white text-xs">{p.driver_code}</span>
              <span className="flex-1 text-gray-500 text-xs truncate">{p.team}</span>
              <span className={`font-bold text-sm ${p.points > 0 ? "text-f1red" : "text-gray-600"}`}>
                {p.points > 0 ? `+${p.points}` : p.retired ? "DNF" : "0"}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="flex rounded overflow-hidden border border-border text-xs mb-2 w-fit">
            {["drivers", "constructors"].map(t => (
              <button key={t} onClick={() => setPointsTab(t)}
                className={`px-2 py-0.5 transition ${pointsTab === t ? "bg-f1red text-white" : "text-gray-400 hover:text-white"}`}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          {pointsTab === "drivers" ? (
            <div className="space-y-1 overflow-auto max-h-72">
              {drivers.length === 0 ? (
                <p className="text-gray-600 text-xs leading-relaxed">
                  Championship data loads from race results. First load may take a moment.
                </p>
              ) : drivers.map(d => (
                <div key={d.driver_code} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5">
                  <span className="w-5 text-gray-500 text-xs">{d.position}</span>
                  <span className="w-8 font-bold text-white text-xs">{d.driver_code}</span>
                  <span className="flex-1 text-gray-500 text-xs truncate">{d.team}</span>
                  <span className="text-f1red font-bold text-sm">{d.points}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-1 overflow-auto max-h-72">
              {constructors.length === 0 ? (
                <p className="text-gray-600 text-xs">No constructor data yet</p>
              ) : constructors.map(c => (
                <div key={c.team} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5">
                  <span className="w-5 text-gray-500 text-xs">{c.position}</span>
                  <span className="flex-1 text-gray-300 text-xs truncate">{c.team}</span>
                  <span className="text-f1red font-bold text-sm">{c.points}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
