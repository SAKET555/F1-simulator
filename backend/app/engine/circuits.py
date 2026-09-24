"""
Circuit layout images, drawn in Python from real GPS position data.

The outline is traced from the X/Y coordinates of a session's fastest lap
(FastF1 position data), then rendered with matplotlib. That data isn't
archived for every session — very recent races and some older ones have no
position data — so when the requested race has none, the same circuit's
other races are tried, newest first. Which race an outline was traced from
is stated on the image.

Results are cached: the traced outline (as a small array) in the shared
persistent cache, and the rendered PNG on disk, so FastF1 is only asked once
per circuit, not once per page view.
"""
from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.core.config import settings
from app.engine import storage
from app.engine.analytics import BG, FG, MUTED

log = logging.getLogger(__name__)

CIRCUIT_IMAGE_VERSION = 1
_MAX_CANDIDATES = 5            # sessions tried per circuit before giving up
_FAIL_RETRY_S = 6 * 3600       # don't hammer FastF1 for a circuit that just failed


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "unknown").lower()).strip("-")


def _image_path(slug: str) -> Path:
    return Path(settings.cache_dir) / "processed" / "charts" / f"circuit_{slug}_v{CIRCUIT_IMAGE_VERSION}.png"


def _trace_outline(year: int, round_number: int) -> Optional[dict]:
    """Fastest-lap X/Y for one session, or None if it has no position data."""
    import fastf1
    from app.engine.data_loader import _ensure_cache_dir

    _ensure_cache_dir()
    try:
        session = fastf1.get_session(year, round_number, "R")
        session.load(laps=True, telemetry=True, weather=False, messages=False)
        lap = session.laps.pick_fastest()
        if lap is None:
            return None
        tel = lap.get_telemetry()
        x = tel["X"].to_numpy(dtype=float)
        y = tel["Y"].to_numpy(dtype=float)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        if len(x) < 50 or (np.ptp(x) == 0 and np.ptp(y) == 0):
            return None
        length_m = float(tel["Distance"].iloc[-1]) if "Distance" in tel else None
        # Light smoothing + thinning: the raw ~10 Hz trace is jittery, and
        # a few hundred points are plenty for a clean outline.
        k = 3
        kernel = np.ones(k) / k
        xs = np.convolve(np.pad(x, (1, 1), mode="edge"), kernel, mode="valid")
        ys = np.convolve(np.pad(y, (1, 1), mode="edge"), kernel, mode="valid")
        return {"x": xs[::2].tolist(), "y": ys[::2].tolist(), "length_m": length_m, "source_year": year}
    except Exception as exc:
        log.info("No position data for %s round %s (%s)", year, round_number, type(exc).__name__)
        return None


def _outline_for(race_id: str, meta: dict) -> Optional[dict]:
    from app.engine.calendar import build_catalogue

    circuit = meta.get("circuit") or race_id
    slug = _slug(circuit)
    key = f"circuit_outline_{slug}"

    cached = storage.load_extra(key)
    if cached is not None:
        if cached.get("ok"):
            return cached
        if time.time() - cached.get("ts", 0) < _FAIL_RETRY_S:
            return None

    same = [r for r in build_catalogue() if r.get("circuit") == meta.get("circuit")]
    # requested race first, then newest → oldest
    same.sort(key=lambda r: (r["race_id"] != race_id, -r["year"]))
    for cand in same[:_MAX_CANDIDATES]:
        outline = _trace_outline(cand["year"], cand["round_number"])
        if outline:
            outline.update(ok=True, source=f"{cand['year']} {cand['event_name']}")
            storage.save_extra(key, outline)
            return outline

    storage.save_extra(key, {"ok": False, "ts": time.time()})
    return None


def _render(outline: dict, meta: dict) -> bytes:
    x = np.array(outline["x"], dtype=float)
    y = np.array(outline["y"], dtype=float)

    fig = Figure(figsize=(7.5, 5.6), dpi=130, facecolor=BG)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.84])
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.plot(x, y, color="#3a3f52", linewidth=11, solid_capstyle="round", solid_joinstyle="round", zorder=1)
    ax.plot(x, y, color="#aab0c0", linewidth=2.2, solid_capstyle="round", solid_joinstyle="round", zorder=2)

    # start / finish line + direction of travel
    ax.scatter([x[0]], [y[0]], s=95, color="#e10600", edgecolors=FG, linewidths=1.4, zorder=4)
    n = min(len(x) - 1, 6)
    ax.annotate("", xy=(x[n], y[n]), xytext=(x[0], y[0]),
                arrowprops={"arrowstyle": "-|>", "color": "#e10600", "lw": 2}, zorder=3)
    pad = 0.06 * max(np.ptp(x), np.ptp(y))
    ax.text(x[0] + pad * 1.6, y[0] + pad * 1.6, "START / FINISH", color="#e10600", fontsize=8, fontweight="bold",
            zorder=5, bbox={"facecolor": BG, "edgecolor": "none", "pad": 2.5})
    ax.set_xlim(x.min() - pad * 2, x.max() + pad * 2)
    ax.set_ylim(y.min() - pad * 2, y.max() + pad * 2)

    title = meta.get("event_name") or meta.get("circuit") or "Circuit"
    fig.text(0.03, 0.94, title, color=FG, fontsize=15, fontweight="bold", va="center")
    bits = [meta.get("circuit") or ""]
    if outline.get("length_m"):
        bits.append(f"≈ {outline['length_m'] / 1000:.2f} km lap")
    fig.text(0.03, 0.885, "  ·  ".join(b for b in bits if b), color=MUTED, fontsize=9.5, va="center")
    fig.text(0.97, 0.015, f"Traced from {outline.get('source', 'GPS data')} fastest lap", color=MUTED,
             fontsize=7.5, ha="right", va="bottom")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    return buf.getvalue()


def circuit_image(race_id: str) -> Optional[bytes]:
    """PNG of this race's circuit layout, or None if no position data exists for it."""
    from app.engine.data_loader import get_race_meta

    meta = get_race_meta(race_id)
    if meta is None:
        return None
    path = _image_path(_slug(meta.get("circuit") or race_id))
    if path.exists():
        return path.read_bytes()

    outline = _outline_for(race_id, meta)
    if outline is None:
        return None
    png = _render(outline, meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return png
