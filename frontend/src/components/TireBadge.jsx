import { TIRE_COLORS } from "../lib/constants";

export default function TireBadge({ compound = "UNKNOWN", age = 0 }) {
  const c = TIRE_COLORS[compound] ?? TIRE_COLORS.UNKNOWN;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-flex items-center justify-center w-[22px] h-[22px] rounded-full text-[11px] font-extrabold ring-2 ring-black/40 ${c.bg} ${c.text}`}
        title={compound}
      >
        {c.label}
      </span>
      <span className="mono text-[11px] text-ink-500">{age}L</span>
    </span>
  );
}
