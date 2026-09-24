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

  const { laps, drivers, gaps_matrix, lap_times_matrix } = data;

  // Show the drivers whose final gap is smallest — the actual competitive
  // battle — rather than an arbitrary slice. A car that fell multiple
  // minutes behind after a long repair stop is real (see below), but it's
  // not a fight worth a line on this chart, and including it by
  // coincidence-of-order would be exactly the kind of arbitrary pick this
  // avoids.
  const lastRow = gaps_matrix[gaps_matrix.length - 1] ?? [];
  const activeDrivers = drivers
    .map((drv, j) => ({ drv, finalGap: lastRow[j] >= 0 ? lastRow[j] : Infinity }))
    .sort((a, b) => a.finalGap - b.finalGap)
    .slice(0, 10)
    .map(d => d.drv);

  const chartData = laps.map((lap, i) => {
    const row = { lap };
    drivers.forEach((drv, j) => {
      const gap = gaps_matrix[i]?.[j] ?? -1;
      row[drv] = gap >= 0 ? gap : null;
      row[`${drv}__lt`] = lap_times_matrix?.[i]?.[j] ?? null;
    });
    return row;
  });

  // A car that loses many minutes to a long pit/repair stop is real data,
  // not a bug (see the backend comment on lap_times_matrix) — but letting
  // it set the axis scale squashes every other driver's actual battle
  // (typically a few tens of seconds) into an unreadable sliver at the
  // bottom. Cap the visible range to the field's normal spread and let an
  // outlier's line simply exit the chart instead of stretching it.
  const typicalGaps = activeDrivers.flatMap(drv => chartData.map(r => r[drv]).filter(v => v != null));
  const p90 = typicalGaps.length
    ? typicalGaps.sort((a, b) => a - b)[Math.floor(typicalGaps.length * 0.9)]
    : 100;
  const yMax = Math.max(30, Math.ceil((p90 * 1.4) / 10) * 10);

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Gap to Leader</h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis dataKey="lap" stroke="#555" tick={{ fill: "#888", fontSize: 10 }}
            label={{ value: "Lap", position: "insideBottom", fill: "#666", fontSize: 10 }} />
          {/* domain capped to the field's normal spread + allowDataOverflow:
              a car that lost minutes to a long repair stop just exits the
              visible area instead of stretching the axis so far that every
              other driver's actual (much closer) battle is unreadable. */}
          <YAxis stroke="#555" tick={{ fill: "#888", fontSize: 10 }}
            domain={[0, yMax]} allowDataOverflow
            tickFormatter={v => `+${v}s`} />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 11 }}
            formatter={(val, name, props) => {
              if (val == null) return ["DNF", name];
              const lt = props.payload?.[`${name}__lt`];
              const ltText = lt != null ? `, lap time ${lt.toFixed(2)}s` : "";
              return [`+${val.toFixed(2)}s${ltText}`, name];
            }}
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
      <p className="text-[10px] text-gray-700 mt-1">
        Showing the closest 10 by final gap · a line running off the top means that car fell further behind than shown (e.g. a long repair stop)
      </p>
    </div>
  );
}
