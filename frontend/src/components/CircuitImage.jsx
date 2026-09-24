import { useEffect, useState } from "react";
import { API_BASE } from "../lib/constants";

/**
 * The circuit layout, drawn server-side in Python (matplotlib) from real GPS
 * position data. It's just the circuit — no cars — and is the same image for
 * every race at that track.
 */
export default function CircuitImage({ raceId }) {
  const [state, setState] = useState("loading");   // loading | ready | missing

  useEffect(() => { setState("loading"); }, [raceId]);

  if (!raceId) return null;

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Circuit</h3>
      {state === "missing" ? (
        <div className="flex items-center justify-center min-h-44 text-gray-600 text-xs text-center px-6 leading-relaxed border border-border rounded-lg">
          No position data is archived for this circuit yet, so its layout can't be drawn.
        </div>
      ) : (
        <div className="relative">
          {state === "loading" && (
            <div className="absolute inset-0 flex items-center justify-center text-gray-600 text-xs">
              Drawing circuit… (first time for a circuit can take ~20s)
            </div>
          )}
          <img
            key={raceId}
            src={`${API_BASE}/races/${raceId}/circuit.png`}
            alt="Circuit layout"
            className={`w-full rounded-lg border border-border transition-opacity ${state === "ready" ? "opacity-100" : "opacity-0 min-h-56"}`}
            onLoad={() => setState("ready")}
            onError={() => setState("missing")}
          />
        </div>
      )}
    </div>
  );
}
