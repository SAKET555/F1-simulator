"""
Continuous trajectory smoothing and off-track excursion detection for one
driver-lap.

Raw position samples arrive a few times a second, metres apart, so a car
drawn straight from them jumps from point to point. They also arrive with
unreliable timing: the merged FastF1 channel can report a car moving under a
metre in 0.12 s and then 19 m in the next 0.2 s while the speed trace reads a
steady 140 km/h. So shape and timing are handled separately:

* Shape: a centripetal Catmull-Rom spline through the samples, parameterised
  by distance along the path (Barry-Goldman form). It passes through every
  sample and, being centripetal, cannot form loops or cusps.
* Timing: distance travelled is integrated from the speed channel (the
  steadier signal) and scaled to the spline's length. The car's position at
  any moment is the point that far along the spline, evaluated on a 60 Hz
  grid, so its motion matches its real speed with no stalls or leaps.
* Heading is the direction of the spline's tangent.

Excursion detection is an ESTIMATE, and the API says so. The timing data has
no kerb or white-line geometry, so the reference is the fastest-lap trace the
circuit map already uses (see circuits.py), smoothed with a closed centripetal
Catmull-Rom spline. That trace is a racing line, not the centreline, so a
"breach" means "the car was more than `threshold_m` to one side of the
reference line", not a verified track-limits violation.

Coordinates from FastF1 are in decimetres; everything returned here is metres.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from scipy.spatial import cKDTree

from app.engine import storage

log = logging.getLogger(__name__)

SAMPLE_HZ = 60.0
DEFAULT_THRESHOLD_M = 5.0      # lateral deviation from the reference line that counts as off-track
MIN_DURATION_S = 0.25          # shorter deviations are treated as GPS noise
MIN_DEPTH_M = 0.75             # likewise for shallow ones
_DM_TO_M = 0.1
_GEOM_PER_SEGMENT = 16         # spline evaluations between neighbouring samples
_CORNER_RADIUS_M = 150.0       # further than this from any numbered corner → label by lap position
_MAX_TRACK_DISTANCE_M = 100.0  # samples further than this from the circuit are feed glitches (pit lanes are closer)
_GLITCH_SLACK_M = 15.0         # allowance on top of speed × time before a jump counts as a teleport
_GAP_FILL_S = 1.0              # longer stretches without valid position are bridged along the reference line


# ── splines ───────────────────────────────────────────────────────────────────

def _catmull_rom(points: np.ndarray, knots: np.ndarray, s: np.ndarray) -> np.ndarray:
    """
    Non-uniform Catmull-Rom (Barry-Goldman) through `points` (N×2) at knot
    values `knots` (strictly increasing, N), evaluated at parameter values `s`
    within [knots[0], knots[-1]]. The ends are extended by reflection.
    """
    P = np.vstack([2 * points[0] - points[1], points, 2 * points[-1] - points[-2]])
    K = np.concatenate([[2 * knots[0] - knots[1]], knots, [2 * knots[-1] - knots[-2]]])
    # segment i spans K[i+1]..K[i+2], using control points i..i+3
    i = np.clip(np.searchsorted(K, s, side="right") - 2, 0, len(K) - 4)
    t0, t1, t2, t3 = (K[i + k][:, None] for k in range(4))
    p0, p1, p2, p3 = (P[i + k] for k in range(4))
    t = s[:, None]
    a1 = ((t1 - t) * p0 + (t - t0) * p1) / (t1 - t0)
    a2 = ((t2 - t) * p1 + (t - t1) * p2) / (t2 - t1)
    a3 = ((t3 - t) * p2 + (t - t2) * p3) / (t3 - t2)
    b1 = ((t2 - t) * a1 + (t - t0) * a2) / (t2 - t0)
    b2 = ((t3 - t) * a2 + (t - t1) * a3) / (t3 - t1)
    return ((t2 - t) * b1 + (t - t1) * b2) / (t2 - t1)


def _centripetal_knots(points: np.ndarray) -> np.ndarray:
    chord = np.hypot(*np.diff(points, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(np.sqrt(np.maximum(chord, 1e-6)))])


def spline_geometry(xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dense points along a centripetal Catmull-Rom through `xy`, and their cumulative arc length (m)."""
    knots = _centripetal_knots(xy)
    s = np.linspace(knots[0], knots[-1], (len(xy) - 1) * _GEOM_PER_SEGMENT + 1)
    dense = _catmull_rom(xy, knots, s)
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(dense, axis=0).T))])
    return dense, arc


def smooth_path(t: np.ndarray, xy: np.ndarray, speed_t: Optional[np.ndarray] = None,
                speed_ms: Optional[np.ndarray] = None, hz: float = SAMPLE_HZ) -> dict:
    """
    Continuous 60 Hz path through coarse (t, x, y) samples.

    The spline's shape comes from `xy`. Position along it at time t is set by
    distance travelled: from the speed trace (`speed_t`, `speed_ms`) when
    given, integrated and scaled so it ends exactly at the end of the spline,
    otherwise from the samples' own times and spacing. Returns t, x, y,
    heading (radians from +x, unwrapped), distance, and the scale applied.
    """
    dense, arc = spline_geometry(xy)
    length = arc[-1]

    scale = 1.0
    time_knots, dist_at_t = t, arc[:: _GEOM_PER_SEGMENT]     # spline distance of each sample
    if speed_t is not None and speed_ms is not None and np.nanmax(speed_ms) > 0:
        v = np.nan_to_num(speed_ms, nan=0.0).clip(min=0.0)
        travelled = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(speed_t))])
        # only the stretch the shape samples cover (glitchy samples at either
        # end of the lap may have been dropped from the shape)
        d0, d1 = np.interp([t[0], t[-1]], speed_t, travelled)
        if d1 > d0:
            scale = length / (d1 - d0)
            time_knots, dist_at_t = speed_t, (travelled - d0) * scale

    grid = np.arange(t[0], t[-1], 1.0 / hz)
    if grid[-1] < t[-1]:
        grid = np.append(grid, t[-1])
    d = np.interp(grid, time_knots, dist_at_t)
    x = np.interp(d, arc, dense[:, 0])
    y = np.interp(d, arc, dense[:, 1])

    # tangent of the spline at that distance (±2 m chord, about a car length
    # overall), which stays smooth even when the car is barely moving
    ahead = np.clip(d + 2.0, 0, length)
    behind = np.clip(d - 2.0, 0, length)
    dx = np.interp(ahead, arc, dense[:, 0]) - np.interp(behind, arc, dense[:, 0])
    dy = np.interp(ahead, arc, dense[:, 1]) - np.interp(behind, arc, dense[:, 1])
    heading = np.unwrap(np.arctan2(dy, dx))
    # Light low-pass on the angle only (Gaussian, sigma ~0.15 s): leftover GPS
    # noise between samples would otherwise make the car's nose twitch. The
    # path itself is not altered.
    sigma = 0.15 * hz
    r = int(3 * sigma)
    kernel = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    heading = np.convolve(np.pad(heading, r, mode="edge"), kernel / kernel.sum(), mode="valid")
    return {"t": grid, "x": x, "y": y, "heading": heading, "distance": d, "distance_scale": float(scale)}


def reference_line(xy: np.ndarray, spacing_m: float = 1.0) -> dict:
    """
    Closed, smoothed reference line resampled every `spacing_m`, with unit
    tangents, left-hand normals and signed curvature (positive = turning left).
    """
    pts = xy
    if np.hypot(*(pts[0] - pts[-1])) < 1e-6:
        pts = pts[:-1]
    # centripetal knots, wrapped so the loop closes smoothly
    closed = np.vstack([pts[-2:], pts, pts[:3]])
    knots = _centripetal_knots(closed)
    s = np.linspace(knots[2], knots[2 + len(pts)], len(pts) * 40, endpoint=False)
    dense = _catmull_rom(closed, knots, s)

    loop = np.vstack([dense, dense[:1]])
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(loop, axis=0).T))])
    total = cum[-1]
    d = np.arange(0.0, total, spacing_m)
    line = np.column_stack([np.interp(d, cum, loop[:, 0]), np.interp(d, cum, loop[:, 1])])

    tan = np.roll(line, -1, axis=0) - np.roll(line, 1, axis=0)
    tan /= np.maximum(np.hypot(*tan.T), 1e-9)[:, None]
    normal = np.column_stack([-tan[:, 1], tan[:, 0]])
    ang = np.unwrap(np.arctan2(tan[:, 1], tan[:, 0]))
    curv = np.gradient(ang) / spacing_m
    k = 9                                    # a few metres of smoothing on curvature
    curv = np.convolve(np.pad(curv, (k, k), mode="wrap"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    return {"xy": line, "tangent": tan, "normal": normal, "curvature": curv, "length_m": float(total)}


# ── lateral offset + excursions ───────────────────────────────────────────────

def lateral_offsets(path_xy: np.ndarray, ref: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Signed distance (m, positive = left of the direction of travel) from each
    path point to the reference line, and the matched reference index.

    Nearest-point matching alone can snap to a different part of the track
    where two sections run close together, so each match is kept near the
    previous one along the lap.
    """
    line = ref["xy"]
    n = len(line)
    dist, cand = cKDTree(line).query(path_xy, k=12)
    window = max(int(0.03 * n), 30)            # ~3 % of a lap either way
    idx = np.empty(len(path_xy), dtype=int)
    prev = int(cand[0, 0])
    for j in range(len(path_xy)):
        c = cand[j]
        gap = np.abs((c - prev + n // 2) % n - n // 2)
        ok = gap <= window
        pick = int(c[ok][np.argmin(dist[j][ok])]) if ok.any() else int(c[0])
        idx[j] = pick
        prev = pick
    offset = np.einsum("ij,ij->i", path_xy - line[idx], ref["normal"][idx])
    return offset, idx


def drop_backtracking(t: np.ndarray, xy: np.ndarray, ref: dict, min_advance_m: float = 2.5) -> np.ndarray:
    """
    Mask of raw samples to shape the spline with: those at least
    `min_advance_m` further along the lap than the last one kept. The merged
    position channel occasionally steps a metre or so back and forth, and in
    slow corners zigzags between samples only ~1 m apart; a spline forced
    through every one of those wiggles bends sharply and the car's heading
    flickers. At racing speed samples are 10-20 m apart, so none are lost.
    """
    _, idx = lateral_offsets(xy, ref)
    n = len(ref["xy"])
    progress = np.unwrap(idx * (2 * np.pi / n)) * (n / (2 * np.pi)) * (ref["length_m"] / n)
    keep = np.zeros(len(t), dtype=bool)
    best = -np.inf
    for i, p in enumerate(progress):
        if i == 0 or p > best + min_advance_m:
            keep[i] = True
            best = p
    keep[-1] = True
    return keep


def drop_glitches(t: np.ndarray, xy: np.ndarray, speed_ms: np.ndarray, ref: dict) -> np.ndarray:
    """
    Mask of raw samples that are physically possible. The position feed
    occasionally teleports - e.g. 2018 Baku lap 40, under a safety car, puts
    every car ~600 m off the circuit for half a minute, with single steps of
    2 km in 0.24 s. Drawn faithfully, those become huge fake excursions. A
    sample is dropped when it is more than `_MAX_TRACK_DISTANCE_M` from any
    part of the track, or further from the last good sample than the car
    could have driven by its own speed trace.
    """
    dist, _ = cKDTree(ref["xy"]).query(xy)
    near = dist <= _MAX_TRACK_DISTANCE_M
    v = np.nan_to_num(speed_ms, nan=0.0).clip(min=0.0)

    def reachable(i: int, j: int) -> bool:
        reach = 1.5 * max(v[i], v[j], 10.0) * abs(t[j] - t[i]) + _GLITCH_SLACK_M
        return bool(np.hypot(*(xy[j] - xy[i])) <= reach)

    cand = np.flatnonzero(near)
    if len(cand) == 0:
        return near
    # Split into runs of consecutive, mutually consistent samples. Start from
    # the longest run (not the first sample: a lap can open with placeholder
    # positions, e.g. near (0, 0), and anchoring on those would reject every
    # real sample after them), then take neighbouring runs outwards, each only
    # if its near end is reachable from the edge of what's already accepted.
    runs, start = [], 0
    for k in range(1, len(cand)):
        if not reachable(cand[k - 1], cand[k]):
            runs.append((start, k - 1))
            start = k
    runs.append((start, len(cand) - 1))
    best = max(range(len(runs)), key=lambda r: runs[r][1] - runs[r][0])
    ok = np.zeros(len(t), dtype=bool)
    ok[cand[runs[best][0]: runs[best][1] + 1]] = True
    left, right = runs[best][0], runs[best][1]
    for a, b in reversed(runs[:best]):
        if reachable(cand[b], cand[left]):
            ok[cand[a: b + 1]] = True
            left = a
    for a, b in runs[best + 1:]:
        if reachable(cand[right], cand[a]):
            ok[cand[a: b + 1]] = True
            right = b
    return ok


def fill_gaps(t: np.ndarray, xy: np.ndarray, ref: dict) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]]:
    """
    Bridge stretches with no valid position (more than `_GAP_FILL_S`) by
    following the reference line between the samples either side, instead of
    letting the spline cut a straight chord across the circuit. Returns the
    extended samples and the (start, end) times of every filled gap, so callers
    can say the car's position there is assumed, not measured.
    """
    _, idx = lateral_offsets(xy, ref)
    n = len(ref["xy"])
    step = max(int(round(8.0 / (ref["length_m"] / n))), 1)        # a point every ~8 m
    out_t, out_xy, gaps = [t[0]], [xy[0]], []
    for i in range(len(t) - 1):
        if t[i + 1] - t[i] > _GAP_FILL_S:
            ahead = (idx[i + 1] - idx[i]) % n
            if 2 * step < ahead < 0.95 * n:
                between = (idx[i] + np.arange(step, ahead - step + 1, step)) % n
                frac = np.arange(step, ahead - step + 1, step) / ahead
                out_t.extend(t[i] + frac * (t[i + 1] - t[i]))
                out_xy.extend(ref["xy"][between])
            gaps.append((float(t[i]), float(t[i + 1])))
        out_t.append(t[i + 1])
        out_xy.append(xy[i + 1])
    return np.asarray(out_t), np.asarray(out_xy), gaps


def _corner_label(ref_idx: int, ref: dict, corners: list[dict]) -> dict:
    if corners:
        p = ref["xy"][ref_idx]
        best = min(corners, key=lambda c: (c["x"] - p[0]) ** 2 + (c["y"] - p[1]) ** 2)
        dist = float(np.hypot(best["x"] - p[0], best["y"] - p[1]))
        if dist <= _CORNER_RADIUS_M:
            return {"corner": f"T{best['number']}{best.get('letter') or ''}", "corner_distance_m": round(dist, 1),
                    "corner_source": "official"}
    pct = 100.0 * ref_idx / len(ref["xy"])
    return {"corner": f"{pct:.0f}% of lap", "corner_distance_m": None, "corner_source": "estimated"}


def find_excursions(t: np.ndarray, offset: np.ndarray, ref_idx: np.ndarray, ref: dict,
                    threshold_m: float, corners: list[dict]) -> list[dict]:
    """Contiguous runs where |offset| > threshold, with entry/exit times, duration and peak depth."""
    out: list[dict] = []
    over = np.abs(offset) > threshold_m
    if not over.any():
        return out

    def cross(i0: int, i1: int) -> float:
        # time |offset| crossed the threshold, interpolated between samples
        o0, o1 = abs(offset[i0]), abs(offset[i1])
        f = 0.0 if o1 == o0 else (threshold_m - o0) / (o1 - o0)
        return float(t[i0] + np.clip(f, 0, 1) * (t[i1] - t[i0]))

    edges = np.flatnonzero(np.diff(np.concatenate([[0], over.astype(int), [0]])))
    for a, b in zip(edges[::2], edges[1::2]):          # run is [a, b)
        depth = np.abs(offset[a:b]) - threshold_m
        k = a + int(np.argmax(depth))
        d_max = float(depth.max())
        t_entry = cross(a - 1, a) if a > 0 else float(t[a])
        t_exit = cross(b - 1, b) if b < len(t) else float(t[b - 1])
        dur = t_exit - t_entry
        if dur < MIN_DURATION_S or d_max < MIN_DEPTH_M:
            continue
        curv = ref["curvature"][ref_idx[k]]
        side_left = offset[k] > 0
        if a == 0 or b == len(t):
            # Runs touching the start or end of the lap are the grid, the
            # pit lane or a lap that ended in the pits, not a track-limit breach.
            kind = "lap start / pit lane"
        elif abs(curv) < 1 / 400:                        # radius > 400 m: effectively a straight
            kind = "off line"
        else:
            kind = "corner cut" if side_left == (curv > 0) else "ran wide"
        out.append({
            "t_entry": round(t_entry, 3), "t_exit": round(t_exit, 3), "t_peak": round(float(t[k]), 3),
            "duration_s": round(dur, 3), "duration_ms": int(round(dur * 1000)),
            "max_excursion_m": round(d_max, 2), "peak_offset_m": round(float(offset[k]), 2),
            "side": "left" if side_left else "right", "kind": kind,
            "i_start": int(a), "i_end": int(b - 1),
            **_corner_label(int(ref_idx[k]), ref, corners),
        })
    return out


# ── data access ───────────────────────────────────────────────────────────────

def _corners_for(meta: dict, outline: dict) -> list[dict]:
    """Numbered corners from FastF1 circuit info for the session the outline was traced from (cached)."""
    from app.engine.circuits import _slug

    key = f"trajectory_corners_{_slug(meta.get('circuit') or '')}"
    cached = storage.load_extra(key)
    if cached is not None:
        return cached
    corners: list[dict] = []
    try:
        import fastf1
        from app.engine.calendar import build_catalogue
        from app.engine.data_loader import _ensure_cache_dir

        _ensure_cache_dir()
        src = next((r for r in build_catalogue() if f"{r['year']} {r['event_name']}" == outline.get("source")), None)
        if src is not None:
            ses = fastf1.get_session(src["year"], src["round_number"], "R")
            ses.load(laps=True, telemetry=False, weather=False, messages=False)
            for r in ses.get_circuit_info().corners.itertuples():
                corners.append({"number": int(r.Number), "letter": str(r.Letter or ""),
                                "x": float(r.X) * _DM_TO_M, "y": float(r.Y) * _DM_TO_M})
    except Exception as exc:
        log.info("No corner info for %s (%s); using lap position instead", outline.get("source"), type(exc).__name__)
    storage.save_extra(key, corners)
    return corners


def _raw_points(points: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = np.array([p["time_s"] for p in points], dtype=float)
    xy = np.array([[p["x"], p["y"]] for p in points], dtype=float) * _DM_TO_M
    v = np.array([p.get("speed_kmh", np.nan) for p in points], dtype=float) / 3.6
    ok = np.isfinite(t) & np.isfinite(xy).all(axis=1) & ~((xy[:, 0] == 0) & (xy[:, 1] == 0))
    t, xy, v = t[ok], xy[ok], v[ok]
    order = np.argsort(t, kind="stable")
    t, xy, v = t[order], xy[order], v[order]
    # merged car/position channels produce near-duplicate timestamps; keep one
    keep = np.concatenate([[True], np.diff(t) > 0.005])
    return t[keep], xy[keep], v[keep]


def _reference(race_id: str) -> Optional[tuple[dict, dict, dict, list[dict]]]:
    """(meta, outline, reference line, corners) for a race, or None without a circuit outline."""
    from app.engine.circuits import _outline_for
    from app.engine.data_loader import get_race_meta

    meta = get_race_meta(race_id)
    if meta is None:
        return None
    outline = _outline_for(race_id, meta)
    if outline is None:
        return None
    ref = reference_line(np.column_stack([outline["x"], outline["y"]]) * _DM_TO_M)
    return meta, outline, ref, _corners_for(meta, outline)


def _smooth_driver(points: list[dict], ref: dict, corners: list[dict], threshold_m: float) -> Optional[dict]:
    """Smoothed path, lateral offsets and excursions for one driver-lap's raw telemetry points."""
    t, xy, v = _raw_points(points)
    if len(t) < 10:
        return None
    good = drop_glitches(t, xy, v, ref)
    if good.sum() < 10:
        return None
    keep = np.zeros(len(t), dtype=bool)
    keep[np.flatnonzero(good)[drop_backtracking(t[good], xy[good], ref)]] = True
    # Times are relative to the lap's first raw sample, so a car whose opening
    # samples were glitches still starts its lap at the right moment; its path
    # simply begins a little later (path t[0] > 0).
    t0 = float(t[0])
    shape_t, shape_xy, gaps = fill_gaps(t[keep], xy[keep], ref)
    # Shape from the good, forward-moving samples; timing from the full speed trace.
    has_speed = np.isfinite(v).any()
    path = smooth_path(shape_t, shape_xy, t if has_speed else None, v if has_speed else None)
    offset, ref_idx = lateral_offsets(np.column_stack([path["x"], path["y"]]), ref)

    rel_gaps = [(a - t0, b - t0) for a, b in gaps]
    path_start = float(path["t"][0] - t0)
    excursions = find_excursions(path["t"] - t0, offset, ref_idx, ref, threshold_m, corners)
    for e in excursions:
        # A run next to missing data (the lap's first valid sample came late,
        # or a gap was filled along the reference line) can't be trusted.
        near_start = path_start > 1.0 and e["t_entry"] - path_start < 1.0
        near_gap = any(e["t_entry"] < b + 1.0 and e["t_exit"] > a - 1.0 for a, b in rel_gaps)
        if near_start or near_gap:
            e["kind"] = "uncertain (near missing data)"
    return {
        "t": t, "xy": xy, "keep": keep, "glitches": int((~good).sum()), "t0": t0, "path": path, "offset": offset,
        "gaps": [(round(a, 3), round(b, 3)) for a, b in rel_gaps],
        "excursions": excursions,
    }


_METHOD = ("Estimated: lateral deviation from the reference fastest-lap line, not official track limits. "
           f"Runs shorter than {MIN_DURATION_S}s or shallower than {MIN_DEPTH_M}m are ignored as GPS noise.")


def _reference_payload(outline: dict, ref: dict, corners: list[dict]) -> dict:
    r2 = lambda a: np.round(a, 2).tolist()
    return {
        "reference_source": outline.get("source"),
        "reference_length_m": round(ref["length_m"], 1),
        "reference": {"x": r2(ref["xy"][::2, 0]), "y": r2(ref["xy"][::2, 1])},
        "corners": [{"label": f"T{c['number']}{c['letter']}", "x": round(c["x"], 1), "y": round(c["y"], 1)}
                    for c in corners],
        "method": _METHOD,
    }


def driver_trajectory(race_id: str, driver: str, lap: int,
                      threshold_m: float = DEFAULT_THRESHOLD_M) -> Optional[dict]:
    """Smoothed 60 Hz path, reference line and estimated excursions for one driver-lap."""
    from app.engine.data_loader import load_telemetry

    base = _reference(race_id)
    if base is None:
        return None
    _, outline, ref, corners = base
    points = load_telemetry(race_id, driver, lap)
    if not points:
        return None
    d = _smooth_driver(points, ref, corners, threshold_m)
    if d is None:
        return None
    t, xy, path, t0 = d["t"], d["xy"], d["path"], d["t0"]

    r2 = lambda a: np.round(a, 2).tolist()
    return {
        "race_id": race_id, "driver": driver, "lap": lap,
        "sample_hz": SAMPLE_HZ,
        "raw_points": int(len(t)), "raw_points_used": int(d["keep"].sum()),
        "raw_hz": round(float((len(t) - 1) / (t[-1] - t[0])), 2),
        "distance_scale": round(path["distance_scale"], 4),
        "threshold_m": threshold_m,
        "max_offset_m": round(float(np.abs(d["offset"]).max()), 2),
        "path": {"t": np.round(path["t"] - t0, 3).tolist(), "x": r2(path["x"]), "y": r2(path["y"]),
                 "heading": np.round(path["heading"], 4).tolist(), "offset": r2(d["offset"])},
        "raw": {"t": np.round(t - t0, 3).tolist(), "x": r2(xy[:, 0]), "y": r2(xy[:, 1])},
        "excursions": d["excursions"],
        **_reference_payload(outline, ref, corners),
    }


# ── every driver on one lap ───────────────────────────────────────────────────

def _lap_telemetry_all(race_id: str, meta: dict, drivers: list[str], lap: int) -> dict[str, list[dict]]:
    """
    Raw telemetry points for every driver on `lap`, in the same format and
    cache entries as data_loader.load_telemetry. Uncached drivers are
    extracted from a single FastF1 session load instead of one per driver.
    """
    out: dict[str, list[dict]] = {}
    missing = []
    for d in drivers:
        cached = storage.load_extra(f"{race_id}_telemetry_{d}_{lap}")
        if cached:
            out[d] = cached
        else:
            missing.append(d)
    if not missing:
        return out

    import fastf1
    from app.engine.data_loader import _ensure_cache_dir

    _ensure_cache_dir()
    session = fastf1.get_session(meta["year"], meta["round_number"], "R")
    session.load(telemetry=True, weather=False, messages=False)
    for d in missing:
        try:
            rows = session.laps.pick_driver(d)
            rows = rows[rows["LapNumber"] == lap]
            if rows.empty:
                continue
            tel = rows.iloc[0].get_telemetry()
            points = []
            for _, row in tel.iterrows():
                tt = row.get("Time")
                points.append({
                    "time_s": tt.total_seconds() if hasattr(tt, "total_seconds") else float(tt),
                    "speed_kmh": float(row.get("Speed", 0) or 0),
                    "throttle": float(row.get("Throttle", 0) or 0) / 100.0,
                    "brake": bool(row.get("Brake", False)),
                    "gear": int(row.get("nGear", 0) or 0),
                    "rpm": int(row.get("RPM", 0) or 0),
                    "drs": int(row.get("DRS", 0) or 0),
                    "x": float(row.get("X", 0) or 0),
                    "y": float(row.get("Y", 0) or 0),
                })
            storage.save_extra(f"{race_id}_telemetry_{d}_{lap}", points)
            out[d] = points
        except Exception as exc:
            log.info("No position data for %s %s lap %d (%s)", race_id, d, lap, type(exc).__name__)
    return out


def lap_trajectories(race_id: str, lap: int, threshold_m: float = DEFAULT_THRESHOLD_M) -> Optional[dict]:
    """
    Every driver's smoothed lap `lap`, on one shared session clock so the cars
    can be replayed together. Each driver's `start` is when they began the lap
    (seconds on that clock, 0 = first car to start it); path times are
    relative to it.
    """
    from app.engine.data_loader import load_session_laps

    base = _reference(race_id)
    if base is None:
        return None
    meta, outline, ref, corners = base
    laps, _ = load_session_laps(race_id)
    on_lap = laps[laps["LapNumber"] == lap]
    if on_lap.empty:
        return None
    # session time at which each driver began this lap = end of their previous lap
    prev = laps[laps["LapNumber"] == lap - 1].set_index("Driver")["Time_s"]
    team = on_lap.set_index("Driver")["Team"].to_dict()
    end_time = on_lap.set_index("Driver")["Time_s"]
    drivers = on_lap.sort_values("Time_s")["Driver"].tolist()        # order they finished the lap
    raw = _lap_telemetry_all(race_id, meta, drivers, lap)

    cars = []
    for d in drivers:
        if d not in raw:
            continue
        s = _smooth_driver(raw[d], ref, corners, threshold_m)
        if s is None:
            continue
        path, t0 = s["path"], s["t0"]
        dur = float(path["t"][-1] - t0)
        if d in prev.index and np.isfinite(prev[d]):
            start = float(prev[d])
        elif np.isfinite(end_time.get(d, np.nan)):
            start = float(end_time[d]) - dur                            # lap 1: work back from its end
        else:
            continue
        r1 = lambda a: np.round(a, 1).tolist()
        cars.append({
            "driver": d, "team": team.get(d, ""), "start": start, "duration": round(dur, 3),
            "t": np.round(path["t"] - t0, 3).tolist(),
            "x": r1(path["x"]), "y": r1(path["y"]),
            "heading": np.round(path["heading"], 3).tolist(),
            "offset": r1(s["offset"]),
            "max_offset_m": round(float(np.abs(s["offset"]).max()), 2),
            "glitch_samples_removed": s["glitches"],
            "gaps": s["gaps"],
            "excursions": s["excursions"],
        })
    if not cars:
        return None
    t_min = min(c["start"] for c in cars)
    for c in cars:
        c["start"] = round(c["start"] - t_min, 3)
    return {
        "race_id": race_id, "lap": lap, "sample_hz": SAMPLE_HZ, "threshold_m": threshold_m,
        "drivers_on_lap": len(drivers), "cars": cars,
        "missing": [d for d in drivers if d not in {c["driver"] for c in cars}],
        **_reference_payload(outline, ref, corners),
    }
