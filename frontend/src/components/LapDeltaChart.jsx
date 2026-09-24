import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, ReferenceLine } from "recharts";

export default function LapDeltaChart({ cars = [] }) {
  const data = cars
    .filter(c => c.lap_time_s && c.lap_time_s < 200)
    .map(c => ({ driver: c.driver_code, time: c.lap_time_s, team: c.team }))
    .sort((a, b) => a.time - b.time);

  if (data.length === 0) return (
    <div className="flex items-center justify-center h-40 text-gray-600 text-sm">No lap time data yet</div>
  );

  const avg = data.reduce((s, d) => s + d.time, 0) / data.length;
  const fastest = data[0]?.time ?? 90;

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Current Lap Times</h3>
      <ResponsiveContainer width="100%" height={Math.max(180, data.length * 18)}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 30, left: 30, bottom: 0 }}>
          <XAxis type="number" domain={[fastest - 1, fastest + 5]}
            tick={{ fill: "#888", fontSize: 9 }} tickFormatter={v => `${v.toFixed(1)}s`} />
          {/* interval={0}: force every driver's tick to render — see
              WinProbabilityChart for why Recharts' default can't be trusted
              not to silently drop rows on a category axis. */}
          <YAxis type="category" dataKey="driver" interval={0} tick={{ fill: "#ccc", fontSize: 10 }} width={28} />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", borderRadius: 8, fontSize: 10 }}
            formatter={(val) => [`${val.toFixed(3)}s`, "Lap time"]}
          />
          <ReferenceLine x={avg} stroke="#555" strokeDasharray="4 2" />
          {/* Animation off: rows re-sort by lap time every tick, and Recharts'
              default tween would otherwise animate a row's bar between two
              unrelated drivers' values as they swap position. */}
          <Bar dataKey="time" radius={[0, 3, 3, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={d.driver} fill={i === 0 ? "#a855f7" : d.time <= avg ? "#22c55e" : "#e10600"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-gray-600 mt-1">Purple = fastest · Green = below avg · Red = above avg</p>
    </div>
  );
}
