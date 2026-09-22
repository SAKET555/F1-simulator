import { useEffect, useState } from "react";
import { Thermometer, Droplets, Wind, CloudRain } from "lucide-react";
import { API_BASE } from "../lib/constants";

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
    <div className="flex items-center gap-4 px-3 py-2 bg-pitwall rounded-lg border border-border text-xs flex-wrap">
      <div className="flex items-center gap-1 text-orange-300">
        <Thermometer size={12} />
        <span>Air {frame.air_temp_c.toFixed(0)}°C</span>
      </div>
      <div className="flex items-center gap-1 text-red-300">
        <Thermometer size={12} />
        <span>Track {frame.track_temp_c.toFixed(0)}°C</span>
      </div>
      <div className="flex items-center gap-1 text-blue-300">
        <Droplets size={12} />
        <span>{frame.humidity.toFixed(0)}%</span>
      </div>
      <div className="flex items-center gap-1 text-gray-400">
        <Wind size={12} />
        <span>{frame.wind_speed_ms.toFixed(1)} m/s</span>
      </div>
      {frame.rainfall && (
        <div className="flex items-center gap-1 text-blue-400 font-bold animate-pulse">
          <CloudRain size={12} />
          <span>RAIN</span>
        </div>
      )}
    </div>
  );
}
