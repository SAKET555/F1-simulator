import { useEffect, useMemo, useRef, useState } from "react";
import { Play, Pause, AlertTriangle, ZoomIn, ZoomOut, Maximize, Crosshair } from "lucide-react";
import { API_BASE } from "../lib/constants";

/**
 * Every driver's lap drawn on the circuit and animated together at display
 * refresh rate.
 *
 * The backend returns each driver's lap already smoothed to a 60 Hz spline
 * (backend/app/engine/trajectory.py), with the time each driver started the
 * lap on a shared clock. Each animation frame advances that clock by the real
 * frame delta-time and interpolates every car between its samples, so motion
 * stays smooth at any refresh rate, playback speed or zoom level.
 * Estimated off-track excursions are drawn as dashed amber segments.
 */

const SPEEDS = [0.5, 1, 2, 4];
const THRESHOLDS = [3, 5, 8];
const TRAIL_S = 2.5;
const MIN_ZOOM = 0.8;
const MAX_ZOOM = 40;

// 20 distinct hues so every driver has their own colour on a dark background
const PALETTE = [
  "#ef4444", "#3b82f6", "#22c55e", "#eab308", "#a855f7", "#06b6d4", "#f97316", "#ec4899", "#84cc16", "#6366f1",
  "#14b8a6", "#f43f5e", "#fde047", "#10b981", "#e879f9", "#38bdf8", "#fb923c", "#a3e635", "#c4b5fd", "#fda4af",
];

const COL = {
  corridor: "rgba(255,255,255,0.07)",
  refLine: "rgba(170,177,196,0.45)",
  excursion: "#f59e0b",
  corner: "rgba(170,177,196,0.85)",
};

const fmtS = (s) => `${s.toFixed(s < 10 ? 2 : 1)}s`;
const fmtClock = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;

function useSize(ref) {
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

// Position / heading / offset of one car at time `local` seconds into its lap.
// car.t[0] can be > 0 when the lap's first position samples were feed glitches.
function sampleCar(car, local, hz) {
  const n = car.t.length;
  const f = Math.min(Math.max((local - car.t[0]) * hz, 0), n - 1);
  const i = Math.min(Math.floor(f), n - 2), a = f - i;
  return {
    i,
    x: car.x[i] + (car.x[i + 1] - car.x[i]) * a,
    y: car.y[i] + (car.y[i + 1] - car.y[i]) * a,
    h: car.heading[i] + (car.heading[i + 1] - car.heading[i]) * a,
    o: car.offset[i] + (car.offset[i + 1] - car.offset[i]) * a,
  };
}

export default function TrajectoryMap({ raceId }) {
  const [lap, setLap] = useState(3);
  const [threshold, setThreshold] = useState(5);
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("idle");          // idle | loading | ready | error
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [focus, setFocus] = useState(null);               // driver code shown in the HUD
  const [follow, setFollow] = useState(false);
  const [selected, setSelected] = useState(null);         // { driver, index } of an excursion
  const [hud, setHud] = useState({ t: 0, onTrack: 0, focus: null });

  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const clockRef = useRef(0);
  const playingRef = useRef(true);
  const speedRef = useRef(1);
  const focusRef = useRef(null);
  const followRef = useRef(false);
  const camRef = useRef({ zoom: 1, cx: 0, cy: 0 });       // zoom factor + world point at canvas centre
  const size = useSize(wrapRef);

  useEffect(() => { playingRef.current = playing; }, [playing]);
  useEffect(() => { speedRef.current = speed; }, [speed]);
  useEffect(() => { focusRef.current = focus; }, [focus]);
  useEffect(() => { followRef.current = follow; }, [follow]);

  const colorOf = useMemo(() => {
    const m = {};
    (data?.cars ?? []).forEach((c, i) => { m[c.driver] = PALETTE[i % PALETTE.length]; });
    return m;
  }, [data]);

  // world bounds + the scale that fits the whole circuit
  const fit = useMemo(() => {
    if (!data || !size.w) return null;
    const xs = data.reference.x, ys = data.reference.y;
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const pad = 28;
    return {
      s: Math.min((size.w - 2 * pad) / (maxX - minX), (size.h - 2 * pad) / (maxY - minY)),
      cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
    };
  }, [data, size]);

  function resetView() {
    if (fit) camRef.current = { zoom: 1, cx: fit.cx, cy: fit.cy };
    setFollow(false);
  }
  useEffect(resetView, [fit]);                             // eslint-disable-line react-hooks/exhaustive-deps

  function zoomBy(factor, sx = size.w / 2, sy = size.h / 2) {
    if (!fit) return;
    const cam = camRef.current;
    const s = fit.s * cam.zoom;
    // keep the world point under (sx, sy) fixed while zooming
    const wx = cam.cx + (sx - size.w / 2) / s;
    const wy = cam.cy - (sy - size.h / 2) / s;
    const zoom = Math.min(Math.max(cam.zoom * factor, MIN_ZOOM), MAX_ZOOM);
    const s2 = fit.s * zoom;
    camRef.current = { zoom, cx: wx - (sx - size.w / 2) / s2, cy: wy + (sy - size.h / 2) / s2 };
  }

  // mouse wheel zoom (native listener so the page doesn't scroll) + drag to pan
  useEffect(() => {
    const el = canvasRef.current;
    if (!el || !fit) return;
    const onWheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    let drag = null;
    const onDown = (e) => { drag = { x: e.clientX, y: e.clientY }; el.setPointerCapture(e.pointerId); };
    const onMove = (e) => {
      if (!drag) return;
      const s = fit.s * camRef.current.zoom;
      camRef.current.cx -= (e.clientX - drag.x) / s;
      camRef.current.cy += (e.clientY - drag.y) / s;
      drag = { x: e.clientX, y: e.clientY };
      if (followRef.current) setFollow(false);
    };
    const onUp = () => { drag = null; };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
    };
  }, [fit, size]);                                         // eslint-disable-line react-hooks/exhaustive-deps

  function load() {
    if (!raceId) return;
    setStatus("loading");
    setError("");
    setSelected(null);
    fetch(`${API_BASE}/races/${raceId}/trajectories?lap=${lap}&threshold_m=${threshold}`)
      .then(async r => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? r.statusText);
        return r.json();
      })
      .then(d => {
        setData(d);
        clockRef.current = 0;
        setFocus(f => (f && d.cars.some(c => c.driver === f)) ? f : d.cars[0]?.driver ?? null);
        setStatus("ready");
      })
      .catch(e => { setData(null); setError(String(e.message ?? e)); setStatus("error"); });
  }

  const clockEnd = useMemo(
    () => (data ? Math.max(...data.cars.map(c => c.start + c.duration)) : 0), [data]);

  // animation loop: advance the shared clock by real frame delta-time
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!data || !fit) {
      canvas?.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    const g = canvas.getContext("2d");
    const hz = data.sample_hz;
    const R = data.reference;
    let raf, last = performance.now(), lastHud = 0;

    const frame = (now) => {
      const dt = Math.min((now - last) / 1000, 0.1);      // clamp after a background tab
      last = now;
      if (playingRef.current) {
        clockRef.current += dt * speedRef.current;
        if (clockRef.current > clockEnd) clockRef.current = 0;
      }
      const clock = clockRef.current;

      // where every car on track is right now
      const live = [];
      for (const car of data.cars) {
        const local = clock - car.start;
        if (local < car.t[0] || local > car.t[car.t.length - 1]) continue;
        live.push({ car, local, s: sampleCar(car, local, hz) });
      }

      // camera (optionally following the focused car)
      const cam = camRef.current;
      if (followRef.current) {
        const f = live.find(l => l.car.driver === focusRef.current);
        if (f) {
          const k = 1 - Math.exp(-dt * 8);
          cam.cx += (f.s.x - cam.cx) * k;
          cam.cy += (f.s.y - cam.cy) * k;
        }
      }
      const sc = fit.s * cam.zoom;
      const px = (x) => (x - cam.cx) * sc + size.w / 2;
      const py = (y) => size.h / 2 - (y - cam.cy) * sc;
      const poly = (xs, ys, i0, i1, close = false) => {
        g.beginPath();
        g.moveTo(px(xs[i0]), py(ys[i0]));
        for (let i = i0 + 1; i <= i1; i++) g.lineTo(px(xs[i]), py(ys[i]));
        if (close) g.closePath();
      };

      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, size.w, size.h);
      g.lineJoin = "round";
      g.lineCap = "round";

      // track corridor (±limit around the reference line) and the line itself
      poly(R.x, R.y, 0, R.x.length - 1, true);
      g.strokeStyle = COL.corridor;
      g.lineWidth = Math.max(2 * data.threshold_m * sc, 3);
      g.stroke();
      g.strokeStyle = COL.refLine;
      g.lineWidth = 1;
      g.setLineDash([4, 4]);
      g.stroke();
      g.setLineDash([]);

      // excursion segments for every driver
      g.strokeStyle = COL.excursion;
      g.lineWidth = 3.5;
      g.setLineDash([6, 4]);
      for (const car of data.cars) {
        for (const e of car.excursions) { poly(car.x, car.y, e.i_start, e.i_end); g.stroke(); }
      }
      g.setLineDash([]);

      g.font = "600 10px Inter, sans-serif";
      g.fillStyle = COL.corner;
      g.textAlign = "center";
      g.textBaseline = "middle";
      for (const k of data.corners) g.fillText(k.label, px(k.x), py(k.y) - 12);

      // trails
      for (const { car, s } of live) {
        const i0 = Math.max(0, s.i - Math.round(TRAIL_S * hz));
        if (s.i <= i0) continue;
        g.globalAlpha = car.driver === focusRef.current ? 0.9 : 0.5;
        poly(car.x, car.y, i0, s.i);
        g.strokeStyle = colorOf[car.driver];
        g.lineWidth = car.driver === focusRef.current ? 3 : 2;
        g.stroke();
      }
      g.globalAlpha = 1;

      // cars: arrow along the heading + 3-letter code; focused car drawn last, on top
      const ordered = [...live].sort((a, b) =>
        (a.car.driver === focusRef.current) - (b.car.driver === focusRef.current));
      for (const { car, local, s } of ordered) {
        const x = px(s.x), y = py(s.y);
        const isFocus = car.driver === focusRef.current;
        const off = car.excursions.some(e => local >= e.t_entry && local <= e.t_exit);
        if (off) {
          g.beginPath();
          g.arc(x, y, 13 + 3 * Math.sin(now / 90), 0, Math.PI * 2);
          g.strokeStyle = COL.excursion;
          g.lineWidth = 2;
          g.stroke();
        }
        const k = isFocus ? 1.35 : 1;
        // inside a gap the position is assumed (along the reference line), not measured
        const noData = (car.gaps ?? []).some(([a, b]) => local > a && local < b);
        g.globalAlpha = noData ? 0.4 : 1;
        g.save();
        g.translate(x, y);
        g.rotate(-s.h);                                     // canvas y is flipped
        g.beginPath();
        g.moveTo(9 * k, 0);
        g.lineTo(-6 * k, 5 * k);
        g.lineTo(-3 * k, 0);
        g.lineTo(-6 * k, -5 * k);
        g.closePath();
        g.fillStyle = colorOf[car.driver];
        g.strokeStyle = isFocus ? "#fff" : "rgba(0,0,0,0.7)";
        g.lineWidth = isFocus ? 1.6 : 1;
        g.fill();
        g.stroke();
        g.restore();

        g.font = `${isFocus ? 800 : 700} ${isFocus ? 12 : 10}px "Barlow Condensed", Inter, sans-serif`;
        const label = noData ? `${car.driver} · no data` : car.driver;
        const w = g.measureText(label).width + 8;
        const lx = x + 10, ly = y - 12;
        g.fillStyle = "rgba(11,13,19,0.8)";
        g.fillRect(lx, ly - 7, w, 14);
        g.fillStyle = colorOf[car.driver];
        g.fillRect(lx, ly - 7, 2, 14);
        g.fillStyle = "#fff";
        g.textAlign = "left";
        g.fillText(label, lx + 5, ly + 0.5);
        g.globalAlpha = 1;
      }

      if (now - lastHud > 100) {                         // HUD text at 10 Hz is plenty
        lastHud = now;
        const f = live.find(l => l.car.driver === focusRef.current);
        setHud({
          t: clock, onTrack: live.length, zoom: cam.zoom,
          focus: f ? {
            local: f.local, offset: f.s.o,
            active: f.car.excursions.findIndex(e => f.local >= e.t_entry && f.local <= e.t_exit),
          } : null,
        });
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [data, fit, size, colorOf, clockEnd]);

  const focusCar = data?.cars.find(c => c.driver === focus) ?? null;
  const activeIdx = hud.focus && hud.focus.active >= 0 ? hud.focus.active : null;
  const hudExIdx = activeIdx ?? (selected && selected.driver === focus ? selected.index : null);
  const ex = focusCar && hudExIdx != null ? focusCar.excursions[hudExIdx] : null;
  const allEx = (data?.cars ?? []).flatMap(c => c.excursions.map((e, index) => ({ ...e, driver: c.driver, index, start: c.start })));

  function jumpTo(e) {
    setFocus(e.driver);
    setSelected({ driver: e.driver, index: e.index });
    clockRef.current = Math.max(0, e.start + e.t_entry - 1.5);
  }

  const iconBtn = "h-8 w-8 inline-flex items-center justify-center rounded-lg bg-[#0b0d13]/80 border border-white/10 hover:border-white/30 text-ink-300 hover:text-white";

  return (
    <div>
      <h3 className="mb-1">Trajectory &amp; track limits</h3>
      <p className="text-[11px] text-ink-500 mb-3 leading-relaxed">
        Every driver on one lap, smoothed from ~7 Hz position samples to continuous 60 Hz splines and replayed together.
        Scroll to zoom, drag to pan. Off-track excursions are <span className="text-amber-400">estimated</span> as
        deviation from a reference fastest-lap line — the timing data has no kerb or white-line geometry.
      </p>

      <div className="flex items-center gap-2 mb-3 flex-wrap text-xs">
        <span className="text-ink-500">Lap</span>
        <input type="number" min={1} max={100} value={lap} onChange={e => setLap(Number(e.target.value))}
          className="w-16 bg-white/[.04] border border-white/10 rounded-lg px-2 py-1.5 text-white" />
        <span className="text-ink-500">Limit</span>
        <select value={threshold} onChange={e => setThreshold(Number(e.target.value))}
          className="bg-white/[.04] border border-white/10 rounded-lg px-2 py-1.5 text-white"
          title="Lateral distance from the reference line that counts as off-track">
          {THRESHOLDS.map(v => <option key={v} value={v}>±{v} m</option>)}
        </select>
        <button onClick={load} disabled={!raceId || status === "loading"}
          className="px-3 py-1.5 bg-f1red hover:bg-red-600 disabled:opacity-40 rounded-lg text-white font-bold">
          {status === "loading" ? "Loading…" : "Load lap"}
        </button>
        {status === "loading" && (
          <span className="text-ink-500">The first load of a race downloads its telemetry — this can take a minute.</span>
        )}
      </div>

      {status === "error" && <p className="text-red-400 text-sm mb-3">{error}</p>}

      <div ref={wrapRef} className="relative w-full h-[520px] rounded-xl bg-black/30 border border-white/[.06] overflow-hidden">
        {status !== "ready" && (
          <div className="absolute inset-0 flex items-center justify-center text-ink-500 text-sm">
            {status === "loading" ? <div className="skeleton absolute inset-4" /> : "Pick a lap, then Load lap."}
          </div>
        )}
        <canvas ref={canvasRef} className="absolute inset-0 w-full h-full cursor-grab active:cursor-grabbing touch-none" />

        {data && status === "ready" && (
          <>
            {/* zoom controls */}
            <div className="absolute top-3 right-3 flex flex-col gap-1.5">
              <button className={iconBtn} onClick={() => zoomBy(1.5)} title="Zoom in"><ZoomIn size={14} /></button>
              <button className={iconBtn} onClick={() => zoomBy(1 / 1.5)} title="Zoom out"><ZoomOut size={14} /></button>
              <button className={iconBtn} onClick={resetView} title="Fit circuit"><Maximize size={14} /></button>
              <button
                className={`${iconBtn} ${follow ? "!border-f1red !text-white bg-f1red/30" : ""}`}
                onClick={() => setFollow(f => !f)} title="Follow the focused driver"
              >
                <Crosshair size={14} />
              </button>
              <span className="mono text-[10px] text-ink-500 text-center">{(hud.zoom ?? 1).toFixed(1)}×</span>
            </div>

            {/* HUD for the focused driver */}
            <div className="absolute top-3 left-3 w-60 rounded-xl bg-[#0b0d13]/85 backdrop-blur border border-white/10 p-3 text-xs pointer-events-none">
              <div className="flex items-baseline justify-between">
                <span className="display font-extrabold text-xl flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ background: colorOf[focus] }} />{focus}
                </span>
                <span className="mono text-ink-300">L{data.lap} · {hud.focus ? fmtClock(hud.focus.local) : "—"}</span>
              </div>
              <p className="mono text-ink-500 mt-0.5">
                {hud.focus
                  ? `off reference line ${hud.focus.offset >= 0 ? "L" : "R"} ${Math.abs(hud.focus.offset).toFixed(1)} m`
                  : "not on this lap right now"}
              </p>
              <div className="mt-2 pt-2 border-t border-white/10">
                {ex ? (
                  <div className={activeIdx != null ? "text-amber-300" : ""}>
                    <p className="flex items-center gap-1 font-bold uppercase tracking-wider text-[10px] text-amber-400">
                      <AlertTriangle size={11} /> {activeIdx != null ? "Off track now" : "Excursion"} · {ex.kind}
                    </p>
                    <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 mt-1">
                      <dt className="text-ink-500">Driver</dt><dd className="mono text-right">{focus}</dd>
                      <dt className="text-ink-500">Corner</dt><dd className="mono text-right">{ex.corner}</dd>
                      <dt className="text-ink-500">Off track</dt><dd className="mono text-right">{fmtS(ex.duration_s)}</dd>
                      <dt className="text-ink-500">Peak</dt><dd className="mono text-right">{ex.max_excursion_m.toFixed(2)} m</dd>
                    </dl>
                  </div>
                ) : (
                  <p className="text-ink-300 leading-snug">
                    {focusCar?.excursions.length
                      ? `${focusCar.excursions.length} excursion(s) this lap — pick one in the table.`
                      : `No excursion beyond ±${data.threshold_m} m. Largest deviation ${focusCar?.max_offset_m.toFixed(1)} m.`}
                  </p>
                )}
              </div>
            </div>

            <div className="absolute bottom-3 left-3 mono text-[10px] text-ink-500 bg-[#0b0d13]/70 rounded px-2 py-1 pointer-events-none">
              {hud.onTrack}/{data.cars.length} on lap {data.lap} · clock {fmtClock(hud.t)}
            </div>
          </>
        )}
      </div>

      {data && status === "ready" && (
        <>
          <div className="flex items-center gap-2 mt-3 text-xs">
            <button onClick={() => setPlaying(p => !p)}
              className="h-8 w-8 inline-flex items-center justify-center rounded-lg bg-white/[.04] border border-white/10 hover:border-white/30">
              {playing ? <Pause size={14} className="text-amber-300" /> : <Play size={14} className="text-emerald-400" />}
            </button>
            <input type="range" min={0} max={clockEnd} step={0.01} value={hud.t}
              onChange={e => { clockRef.current = Number(e.target.value); setHud(h => ({ ...h, t: Number(e.target.value) })); }}
              className="flex-1 accent-[#e10600]" />
            <div className="inline-flex p-0.5 rounded-lg bg-white/[.04] border border-white/10">
              {SPEEDS.map(v => (
                <button key={v} onClick={() => setSpeed(v)}
                  className={`px-2 h-7 rounded-md mono font-bold ${speed === v ? "bg-f1red text-white" : "text-ink-300 hover:text-white"}`}>
                  {v}×
                </button>
              ))}
            </div>
          </div>

          {/* legend: click a driver to focus (and follow) them */}
          <div className="flex flex-wrap gap-1.5 mt-3">
            {data.cars.map(c => (
              <button key={c.driver} onClick={() => setFocus(c.driver)}
                className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-bold border transition-colors ${
                  focus === c.driver ? "border-white/60 bg-white/10 text-white" : "border-white/10 text-ink-300 hover:text-white"
                }`}>
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: colorOf[c.driver] }} />
                {c.driver}
                {c.excursions.length > 0 && <span className="text-amber-400">·{c.excursions.length}</span>}
              </button>
            ))}
          </div>

          {allEx.length > 0 && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-ink-500 text-left border-b border-white/10">
                    <th className="pb-1.5 pr-2 font-medium">Driver</th>
                    <th className="pb-1.5 pr-2 font-medium">Corner</th>
                    <th className="pb-1.5 pr-2 font-medium">Type</th>
                    <th className="pb-1.5 pr-2 font-medium text-right">Entry</th>
                    <th className="pb-1.5 pr-2 font-medium text-right">Rejoin</th>
                    <th className="pb-1.5 pr-2 font-medium text-right">Δt</th>
                    <th className="pb-1.5 font-medium text-right">Peak depth</th>
                  </tr>
                </thead>
                <tbody>
                  {allEx.map((e, i) => (
                    <tr key={i} onClick={() => jumpTo(e)}
                      className={`border-b border-white/5 cursor-pointer hover:bg-white/[.05] ${
                        selected?.driver === e.driver && selected?.index === e.index ? "bg-amber-500/10" : ""}`}>
                      <td className="py-1.5 pr-2">
                        <span className="inline-flex items-center gap-1.5 font-bold">
                          <span className="w-2 h-2 rounded-sm" style={{ background: colorOf[e.driver] }} />{e.driver}
                        </span>
                      </td>
                      <td className="py-1.5 pr-2 mono">{e.corner}</td>
                      <td className="py-1.5 pr-2 text-ink-300">{e.kind}</td>
                      <td className="py-1.5 pr-2 mono text-right">{fmtClock(e.t_entry)}</td>
                      <td className="py-1.5 pr-2 mono text-right">{fmtClock(e.t_exit)}</td>
                      <td className="py-1.5 pr-2 mono text-right">{e.duration_ms} ms</td>
                      <td className="py-1.5 mono text-right text-amber-300">{e.max_excursion_m.toFixed(2)} m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="text-[10px] text-ink-500 mt-3 leading-relaxed">
            {data.cars.length} of {data.drivers_on_lap} drivers on lap {data.lap}
            {data.missing.length ? ` (no position data for ${data.missing.join(", ")})` : ""}.
            {(() => {
              const n = data.cars.reduce((s, c) => s + (c.glitch_samples_removed ?? 0), 0);
              return n ? ` ${n} impossible position samples (feed glitches) were removed before smoothing.` : "";
            })()}{" "}
            Reference line: {data.reference_source} fastest lap. {data.method}
            {data.corners.length === 0 ? " Corner numbers unavailable; positions shown as % of lap." : ""}
          </p>
        </>
      )}
    </div>
  );
}
