import TireBadge from "./TireBadge";

function GapDisplay({ gap }) {
  if (gap === 0) return <span className="text-f1red font-bold text-xs">LEADER</span>;
  return <span className="text-gray-300 text-xs">+{gap.toFixed(3)}s</span>;
}

export default function Leaderboard({ cars = [], lap, totalLaps }) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-widest">
          Leaderboard
        </h2>
        {lap != null && (
          <span className="text-xs text-gray-500">
            Lap <span className="text-white font-bold">{lap}</span>/{totalLaps}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-1">
        {cars.length === 0 && (
          <p className="text-gray-600 text-sm text-center mt-8">Waiting for race data…</p>
        )}
        {cars.map((car, idx) => (
          <div
            key={car.car_id}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm
              ${idx === 0 ? "bg-panel border border-f1red/40" : "bg-panel/60"}
              hover:bg-panel transition-colors`}
          >
            {/* Position */}
            <span
              className={`w-6 text-center font-bold ${
                idx === 0 ? "text-f1red" : idx < 3 ? "text-yellow-400" : "text-gray-400"
              }`}
            >
              {car.position}
            </span>

            {/* Driver */}
            <span className="w-10 font-mono font-bold text-white text-xs tracking-wider">
              {car.driver_code}
            </span>

            {/* Team */}
            <span className="flex-1 text-gray-500 text-xs truncate">{car.team}</span>

            {/* Tyre */}
            <TireBadge compound={car.tire_compound} age={car.tire_age_laps} />

            {/* Gap */}
            <div className="w-20 text-right">
              <GapDisplay gap={car.gap_to_leader_s} />
            </div>

            {/* Pit indicator */}
            {car.is_in_pit && (
              <span className="text-xs bg-blue-700 text-white px-1 rounded">PIT</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
