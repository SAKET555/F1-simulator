import { useEffect, useState } from "react";
import { Thermometer, Droplets, Wind, CloudRain } from "lucide-react";
import { API_BASE } from "../lib/constants";

function Tile({ icon: Icon, label, value, tone }) {
  return (
    <div className="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-white/[.03] border border-white/[.07] min-w-[120px]">
      <span className={`inline-flex items-center justify-center w-7 h-7 rounded-lg bg-white/[.05] ${tone}`}>
        <Icon size={14} />
      </span>
      <div className="leading-tight">
        <p className="text-[9px] uppercase tracking-[.2em] text-ink-500">{label}</p>
        <p className="mono text-sm font-bold text-white">{value}</p>
      </div>
    </div>
  );
}

export default function WeatherWidget({ raceId, currentLap = 1 }) {
  const [frames, setFrames] = useState([]);

  useEffect(() => {
    if (!raceId) return;
    fetch(`${API_BASE}/races/${raceId}/weather`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => setFrames(d.frames || []))
      .catch(() => setFrames([]));
  }, [raceId]);

  if (!frames.length) return null;

  const frame = frames.reduce((best, f) =>
    Math.abs(f.lap - currentLap) < Math.abs(best.lap - currentLap) ? f : best
  , frames[0]);

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <Tile icon={Thermometer} label="Air"      value={`${frame.air_temp_c.toFixed(0)}°C`}   tone="text-orange-300" />
      <Tile icon={Thermometer} label="Track"    value={`${frame.track_temp_c.toFixed(0)}°C`} tone="text-red-400" />
      <Tile icon={Droplets}    label="Humidity" value={`${frame.humidity.toFixed(0)}%`}      tone="text-sky-300" />
      <Tile icon={Wind}        label="Wind"     value={`${frame.wind_speed_ms.toFixed(1)} m/s`} tone="text-ink-300" />
      {frame.rainfall && (
        <span className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-sky-500/15 border border-sky-500/40 text-sky-300 text-xs font-bold animate-pulse">
          <CloudRain size={14} /> RAIN
        </span>
      )}
    </div>
  );
}
