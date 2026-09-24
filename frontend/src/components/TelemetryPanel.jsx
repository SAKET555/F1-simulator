import { useState, useEffect } from "react";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer
} from "recharts";
import { API_BASE } from "../lib/constants";

export default function TelemetryPanel({ raceId, cars = [] }) {
  const [selectedDriver, setSelectedDriver] = useState("");
  const [lapNumber, setLapNumber] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (cars.length > 0 && !selectedDriver) {
      setSelectedDriver(cars[0].driver_code);
    }
  }, [cars]);

  function fetchTelemetry() {
    if (!raceId || !selectedDriver) return;
    setLoading(true);
    setAttempted(true);
    setError(false);
    fetch(`${API_BASE}/races/${raceId}/telemetry?driver=${selectedDriver}&lap=${lapNumber}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setData(null); setLoading(false); setError(true); });
  }

  const chartData = data?.points?.map(p => ({
    time: parseFloat(p.time_s.toFixed(1)),
    speed: p.speed_kmh,
    throttle: p.throttle * 100,
    brake: p.brake ? 100 : 0,
    gear: p.gear,
    drs: p.drs > 0 ? 10 : 0,
  })) ?? [];

  const uniqueDrivers = [...new Set(cars.map(c => c.driver_code))];

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Circuit Telemetry</h3>

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <select
          className="bg-pitwall border border-border rounded px-2 py-1 text-xs text-white"
          value={selectedDriver}
          onChange={e => setSelectedDriver(e.target.value)}
        >
          {uniqueDrivers.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <span className="text-gray-500 text-xs">Lap</span>
        <input
          type="number"
          min={1}
          max={80}
          value={lapNumber}
          onChange={e => setLapNumber(parseInt(e.target.value) || 1)}
          className="w-14 bg-pitwall border border-border rounded px-2 py-1 text-xs text-white"
        />
        <button
          onClick={fetchTelemetry}
          disabled={loading}
          className="px-3 py-1 bg-f1red text-white text-xs rounded hover:bg-red-700 transition disabled:opacity-50"
        >
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {chartData.length === 0 ? (
        <div className="flex items-center justify-center h-48 text-gray-600 text-sm text-center px-6 leading-relaxed">
          {!attempted
            ? "Select a driver and lap then click Load"
            : error
              ? "Couldn't load telemetry for this session — it may not be archived yet (common for very recent events)"
              : "No telemetry recorded for that driver on that lap — try another lap"}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
            <XAxis dataKey="time" stroke="#555" tick={{ fill: "#888", fontSize: 9 }}
              label={{ value: "Time (s)", position: "insideBottom", fill: "#666", fontSize: 10 }} />
            <YAxis yAxisId="speed" domain={[0, 370]} stroke="#3b82f6" tick={{ fill: "#888", fontSize: 9 }} />
            <YAxis yAxisId="pct" orientation="right" domain={[0, 120]} stroke="#22c55e"
              tick={{ fill: "#888", fontSize: 9 }} tickFormatter={v => `${v}%`} />
            <Tooltip
              contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 10 }}
              formatter={(val, name) => {
                if (name === "speed") return [`${val.toFixed(0)} km/h`, "Speed"];
                if (name === "throttle") return [`${val.toFixed(0)}%`, "Throttle"];
                if (name === "brake") return [val > 0 ? "ON" : "off", "Brake"];
                if (name === "gear") return [val, "Gear"];
                return [val, name];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Area yAxisId="speed" type="monotone" dataKey="speed" fill="#1d4ed8" stroke="#3b82f6"
              fillOpacity={0.3} strokeWidth={1.5} dot={false} name="speed" />
            <Area yAxisId="pct" type="monotone" dataKey="throttle" fill="#15803d" stroke="#22c55e"
              fillOpacity={0.3} strokeWidth={1} dot={false} name="throttle" />
            <Area yAxisId="pct" type="monotone" dataKey="brake" fill="#dc2626" stroke="#ef4444"
              fillOpacity={0.4} strokeWidth={0} dot={false} name="brake" />
            <Line yAxisId="pct" type="monotone" dataKey="gear" stroke="#eab308"
              strokeWidth={1} dot={false} name="gear" />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
