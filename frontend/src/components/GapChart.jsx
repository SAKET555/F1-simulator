import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from "recharts";
import { API_BASE } from "../lib/constants";

const CHART_COLORS = [
  "#e10600","#00d2be","#1e6fff","#ff8700","#dc0000",
  "#ffffff","#358c75","#b6babd","#0090ff","#2b4562",
  "#c92d4b","#f596c8","#aabb01","#87ceeb","#ff7043",
  "#9c27b0","#4caf50","#ff5722","#795548","#607d8b",
];

export default function GapChart({ raceId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!raceId) return;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/races/${raceId}/gaps`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  }, [raceId]);

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
      Loading gap history…
    </div>
  );
  if (error) return (
    <div className="flex items-center justify-center h-64 text-red-400 text-sm">
      Could not load gap data
    </div>
  );
  if (!data) return null;

  const { laps, drivers, gaps_matrix } = data;
  const activeDrivers = drivers.slice(0, 10);

  const chartData = laps.map((lap, i) => {
    const row = { lap };
    drivers.forEach((drv, j) => {
      const gap = gaps_matrix[i]?.[j] ?? -1;
      row[drv] = gap >= 0 ? gap : null;
    });
    return row;
  });

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Gap to Leader</h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis dataKey="lap" stroke="#555" tick={{ fill: "#888", fontSize: 10 }}
            label={{ value: "Lap", position: "insideBottom", fill: "#666", fontSize: 10 }} />
          <YAxis stroke="#555" tick={{ fill: "#888", fontSize: 10 }}
            tickFormatter={v => `+${v}s`} />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 11 }}
            formatter={(val, name) => [val != null ? `+${val.toFixed(2)}s` : "DNF", name]}
            labelFormatter={l => `Lap ${l}`}
          />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          {activeDrivers.map((drv, i) => (
            <Line
              key={drv}
              type="monotone"
              dataKey={drv}
              stroke={CHART_COLORS[i % CHART_COLORS.length]}
              dot={false}
              strokeWidth={1.5}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
