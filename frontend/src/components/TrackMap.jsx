import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

function normalize(points, w, h, padding = 20) {
  if (!points.length) return [];
  const xs = points.map(p => p.x);
  const ys = points.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  // A single, uniform scale for both axes — not one scale per axis. Scaling
  // x and y independently stretches/squashes the shape to fit the box's
  // aspect ratio, which is almost never the real circuit's aspect ratio, so
  // the "track" ends up looking nothing like the real layout. One shared
  // scale (the tighter of the two) preserves the actual shape; the result
  // is then centered in the remaining space instead of hugging one corner.
  const availW = w - 2 * padding;
  const availH = h - 2 * padding;
  const scale = Math.min(availW / rangeX, availH / rangeY);
  const drawnW = rangeX * scale;
  const drawnH = rangeY * scale;
  const offsetX = padding + (availW - drawnW) / 2;
  const offsetY = padding + (availH - drawnH) / 2;

  return points.map(p => ({
    ...p,
    nx: offsetX + (p.x - minX) * scale,
    // SVG y grows downward; track telemetry y typically doesn't, so flip it
    // rather than rendering the circuit mirrored top-to-bottom.
    ny: offsetY + (maxY - p.y) * scale,
  }));
}

export default function TrackMap({ raceId, cars = [], currentLap }) {
  const [trackPoints, setTrackPoints] = useState([]);
  const [loading, setLoading] = useState(false);
  const W = 320, H = 220;

  const leaderCode = cars[0]?.driver_code;

  useEffect(() => {
    if (!raceId || !leaderCode) return;
    setLoading(true);
    fetch(`${API_BASE}/races/${raceId}/telemetry?driver=${leaderCode}&lap=${currentLap || 1}`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => {
        const pts = (d.points || []).filter((_, i) => i % 5 === 0);
        setTrackPoints(normalize(pts, W, H));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [raceId, leaderCode]);

  if (loading) return (
    <div className="flex items-center justify-center h-44 text-gray-600 text-sm">Loading track…</div>
  );
  if (!trackPoints.length) return (
    <div className="flex items-center justify-center h-44 text-gray-600 text-xs text-center px-6 leading-relaxed">
      No telemetry archived for this session yet — the track map needs it to draw the circuit
    </div>
  );

  const pathD = trackPoints
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.nx.toFixed(1)},${p.ny.toFixed(1)}`)
    .join(" ") + " Z";

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Track Map</h3>
      <svg width={W} height={H} className="rounded-lg bg-pitwall border border-border">
        <path d={pathD} fill="none" stroke="#3a3d4a" strokeWidth={12} strokeLinecap="round" strokeLinejoin="round" />
        <path d={pathD} fill="none" stroke="#555" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

        {/* Cars a lap or more down don't have a real time gap to position
            from (the backend sends a sentinel there deliberately — see
            Leaderboard/_build_car_states for why), so there's no reliable
            proxy for where they actually are on track; skip drawing them
            rather than placing them somewhere meaningless. */}
        {cars.filter(c => !c.retired && !c.laps_down).slice(0, 10).map((car, idx) => {
          // Approximate each car's point on the leader's lap trace from its
          // gap to the leader, as a fraction of one lap.
          const lapDurationS = cars[0]?.lap_time_s || 90;
          const lapFraction = 1 - ((car.gap_to_leader_s % lapDurationS) / lapDurationS);
          const ptIdx = Math.floor(lapFraction * trackPoints.length) % trackPoints.length;
          const pt = trackPoints[ptIdx];
          if (!pt) return null;
          return (
            <g key={car.car_id}>
              <circle cx={pt.nx} cy={pt.ny} r={5} fill={idx === 0 ? "#e10600" : "#fff"} opacity={0.9} />
              {/* Stroked "halo" behind the initials so they stay legible over
                  the track line and other cars regardless of what's underneath. */}
              <text x={pt.nx + 7} y={pt.ny + 3} fontSize={9} fontWeight={700}
                stroke="#0b0d13" strokeWidth={3} paintOrder="stroke" fill="#fff">
                {car.driver_code}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="text-[10px] text-gray-700 mt-1">Positions are approximate (gap-based)</p>
    </div>
  );
}
