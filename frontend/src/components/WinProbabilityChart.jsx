import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer, LabelList,
} from "recharts";

const COLORS = [
  "#e10600", "#3b82f6", "#f59e0b", "#10b981",
  "#8b5cf6", "#ec4899", "#06b6d4", "#f97316",
  "#84cc16", "#a1a1aa",
];

export default function WinProbabilityChart({ predictions }) {
  if (!predictions?.probabilities?.length) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        Awaiting simulation data...
      </div>
    );
  }

  const data = predictions.probabilities
    .slice(0, 10)
    .map((p) => ({ name: p.driver_code, win: p.win_pct, podium: p.podium_pct, car_id: p.car_id }))
    .sort((a, b) => b.win - a.win);

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest">
          Win Probability
        </h2>
        <span className="text-xs text-gray-600">
          Lap {predictions.lap} &middot; n={predictions.n_simulations}
        </span>
      </div>

      {/* Main horizontal bar chart */}
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 40, top: 4, bottom: 4 }}>
          <XAxis
            type="number"
            domain={[0, 100]}
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickFormatter={(v) => `${v}%`}
          />
          {/* interval={0}: without it, Recharts guesses which category ticks
              would overlap and silently drops the rest — including, at one
              point, row 0 (the actual leader), which is exactly the name
              this chart most needs to show. The chart is sized with plenty
              of room per row, so force every tick to render. */}
          <YAxis
            type="category"
            dataKey="name"
            interval={0}
            tick={{ fill: "#d1d5db", fontSize: 11, fontWeight: 700 }}
            width={34}
          />
          <Tooltip
            formatter={(value, name) => [`${value.toFixed(1)}%`, name === "Win" ? "Win" : "Podium"]}
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: "#fff" }}
          />
          {/* Animation off: this chart re-sorts by win% on every lap tick, so
              Recharts' default row-index-based tween would otherwise animate
              a row's bar from its *previous* occupant's width to the new
              one, flashing an oversized, momentarily-unlabeled bar. */}
          <Bar dataKey="win" name="Win" radius={[0, 4, 4, 0]} isAnimationActive={false}>
            {data.map((entry, i) => (
              <Cell key={entry.car_id} fill={COLORS[i % COLORS.length]} />
            ))}
            <LabelList
              dataKey="win"
              position="right"
              formatter={(v) => `${v.toFixed(1)}%`}
              style={{ fill: "#9ca3af", fontSize: 10 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Podium probability mini-bar chart */}
      <div>
        <p className="text-xs text-gray-500 mb-2">Podium probability</p>
        <div className="flex items-end gap-1">
          {data.map((d, i) => {
            const h = Math.max(Math.round((d.podium / 100) * 56), 2);
            return (
              <div key={d.car_id} className="flex flex-col items-center gap-0.5">
                <span className="text-[9px] text-gray-500">{d.podium > 5 ? `${d.podium.toFixed(0)}%` : ""}</span>
                <div
                  className="w-7 rounded-t"
                  style={{ height: h, background: COLORS[i % COLORS.length], opacity: 0.75 }}
                />
                <span className="text-[9px] text-gray-400 font-bold">{d.name}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
