import { TIRE_COLORS } from "../lib/constants";

export default function TireBadge({ compound = "UNKNOWN", age = 0 }) {
  const c = TIRE_COLORS[compound] ?? TIRE_COLORS.UNKNOWN;
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold ${c.bg} ${c.text}`}
        title={compound}
      >
        {c.label}
      </span>
      <span className="text-xs text-gray-400">{age}L</span>
    </span>
  );
}
