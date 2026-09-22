import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

export default function ChampionshipPanel({ year }) {
  const [tab, setTab] = useState("drivers");
  const [drivers, setDrivers] = useState([]);
  const [constructors, setConstructors] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!year) return;
    setLoading(true);
    Promise.all([
      fetch(`${API_BASE}/championship/${year}/drivers`).then(r => r.ok ? r.json() : []).catch(() => []),
      fetch(`${API_BASE}/championship/${year}/constructors`).then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([d, c]) => {
      setDrivers(Array.isArray(d) ? d : []);
      setConstructors(Array.isArray(c) ? c : []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [year]);

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex-1">
          {year} Championship
        </h3>
        <div className="flex rounded overflow-hidden border border-border text-xs">
          {["drivers", "constructors"].map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-2 py-0.5 transition ${tab === t ? "bg-f1red text-white" : "text-gray-400 hover:text-white"}`}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-32 text-gray-600 text-xs">Loading standings…</div>
      ) : tab === "drivers" ? (
        <div className="space-y-1 overflow-auto max-h-72">
          {drivers.length === 0 ? (
            <p className="text-gray-600 text-xs leading-relaxed">
              Championship data loads from FastF1 session results. First load may take a moment.
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
    </div>
  );
}
