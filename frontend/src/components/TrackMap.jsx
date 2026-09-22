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
  return points.map(p => ({
    ...p,
    nx: padding + ((p.x - minX) / rangeX) * (w - 2 * padding),
    ny: padding + ((p.y - minY) / rangeY) * (h - 2 * padding),
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
    <div className="flex items-center justify-center h-44 text-gray-600 text-xs">
      Track map loads after telemetry is available
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

        {cars.slice(0, 10).map((car, idx) => {
          const lapFraction = Math.max(0, 1 - (car.gap_to_leader_s / 120));
          const ptIdx = Math.floor(lapFraction * trackPoints.length) % trackPoints.length;
          const pt = trackPoints[ptIdx];
          if (!pt) return null;
          return (
            <g key={car.car_id}>
              <circle cx={pt.nx} cy={pt.ny} r={5} fill={idx === 0 ? "#e10600" : "#fff"} opacity={0.9} />
              <text x={pt.nx + 6} y={pt.ny + 3} fontSize={7} fill="#ccc">{car.driver_code}</text>
            </g>
          );
        })}
      </svg>
      <p className="text-[10px] text-gray-700 mt-1">Positions are approximate (gap-based)</p>
    </div>
  );
}
