"""
Race analytics — statistics and charts computed with pandas and rendered
with matplotlib, entirely server-side in Python.

Everything here reads the same persistently-cached lap DataFrame the replay
engine uses (load_session_laps), so it costs no extra FastF1 calls.

Two small pieces of method worth knowing before reading the charts:

* "Neutralised" laps (safety car / VSC / red-flag) are detected from the
  field itself: a lap where the *median* clean lap time across all cars is
  well above the race's normal pace is a lap where everyone was slow, which
  is not something a driver did. They're excluded from every pace and
  consistency figure, and shaded on the lap-time chart.
* Comparisons across time (tyre age, consistency) are made *relative to the
  field on the same lap*, which cancels fuel burn, track evolution and
  neutralisations — the things that make raw lap times across a race
  incomparable.
"""
from __future__ import annotations

import io
import logging
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.core.config import settings

log = logging.getLogger(__name__)

# Bump when a chart's meaning/appearance changes so cached PNGs are rebuilt.
ANALYTICS_VERSION = 2

# ── theme (matches the app's dark panels) ─────────────────────────────────────
BG, FG, MUTED, GRID = "#1a1d27", "#e5e7eb", "#8b90a0", "#2a2d3a"

COMPOUND_COLORS = {
    "SOFT": "#ef4444", "MEDIUM": "#facc15", "HARD": "#e5e7eb",
    "INTERMEDIATE": "#22c55e", "WET": "#3b82f6", "UNKNOWN": "#6b7280",
}

# Substring → colour, chosen to stay legible on a dark background.
_TEAM_COLORS = [
    ("red bull", "#3671c6"), ("ferrari", "#e8002d"), ("mercedes", "#27f4d2"),
    ("mclaren", "#ff8000"), ("aston", "#229971"), ("alpine", "#0090ff"),
    ("williams", "#64c4ff"), ("racing bulls", "#6692ff"), ("alphatauri", "#6692ff"),
    ("toro rosso", "#6692ff"), ("visa", "#6692ff"), ("audi", "#d0d0d0"),
    ("sauber", "#52e252"), ("alfa", "#c92d4b"), ("haas", "#b6babd"),
    ("cadillac", "#c8a951"), ("renault", "#ffd800"), ("racing point", "#f596c8"),
    ("force india", "#f596c8"), ("lotus", "#4caf50"),
]
_FALLBACK_TEAM_COLOR = "#9ca3af"


def team_color(team: str) -> str:
    t = (team or "").lower()
    for key, color in _TEAM_COLORS:
        if key in t:
            return color
    return _FALLBACK_TEAM_COLOR


# ── prepared data ─────────────────────────────────────────────────────────────

class RaceData:
    """Everything the charts and stats need, derived once per race."""

    def __init__(self, race_id: str):
        from app.engine.data_loader import load_session_laps, get_race_meta
        from app.engine.replay import _build_car_states

        laps, total_laps = load_session_laps(race_id)
        self.race_id = race_id
        self.meta = get_race_meta(race_id) or {}
        self.total_laps = total_laps
        self.laps = laps.copy()

        last_lap = int(laps["LapNumber"].max())
        cars = _build_car_states(laps[laps["LapNumber"] == last_lap].copy(), laps, last_lap)
        self.cars = sorted(cars, key=lambda c: c.position)
        self.order = [c.driver_code for c in self.cars]                   # final classification
        self.finishers = [c.driver_code for c in self.cars if not c.retired]
        self.team = {c.driver_code: c.team for c in self.cars}
        self.position = {c.driver_code: c.position for c in self.cars}

        # Clean racing laps: has a time, not a pit in/out lap.
        clean = self.laps[
            self.laps["LapTime_s"].notna() & ~self.laps["IsPitIn"] & ~self.laps["IsPitOut"]
        ]
        lap_med = clean.groupby("LapNumber")["LapTime_s"].median()
        base = float(lap_med.quantile(0.25)) if len(lap_med) else 90.0
        self.base_pace = base
        # A lap where the whole field is slow is neutralised, not "slow driving".
        self.neutral_laps = sorted(int(l) for l in lap_med[lap_med > 1.12 * base].index)

        # Also drop the laps either side of a neutralisation: the lap it's
        # deployed on is part-slow, and the restart lap is slow for everyone
        # (cars bunched up, tyres cold) — neither is a pace signal.
        neutral = set(self.neutral_laps)
        edge_laps = ({l - 1 for l in neutral} | {l + 1 for l in neutral}) - neutral
        clean = clean[~clean["LapNumber"].isin(neutral | edge_laps)]
        clean = clean[clean["LapTime_s"] < 1.15 * base].copy()
        # Pace relative to the field on the same lap, and relative to the
        # driver's own typical offset — isolates tyre/consistency effects.
        field_med = clean.groupby("LapNumber")["LapTime_s"].transform("median")
        clean["field_delta"] = clean["LapTime_s"] - field_med
        clean["rel_delta"] = clean["field_delta"] - clean.groupby("Driver")["field_delta"].transform("median")
        self.clean = clean

        # Session-elapsed time per (lap, driver) → race position and gaps by lap.
        self.time_by_lap = self.laps.pivot_table(
            index="LapNumber", columns="Driver", values="Time_s", aggfunc="first"
        ).sort_index()
        self.rank_by_lap = self.time_by_lap.rank(axis=1, method="min")
        self.gap_by_lap = self.time_by_lap.sub(self.time_by_lap.min(axis=1), axis=0)

        self.pit_laps: dict[str, list[int]] = (
            self.laps[self.laps["IsPitIn"]].groupby("Driver")["LapNumber"].apply(list).to_dict()
        )

    def style(self, drv: str) -> dict:
        """Line colour + style; a team's second driver is dashed."""
        team = self.team.get(drv, "")
        mates = [d for d in self.order if self.team.get(d) == team]
        idx = mates.index(drv) if drv in mates else 0
        return {"color": team_color(team), "linestyle": "-" if idx == 0 else (0, (4, 2))}


@lru_cache(maxsize=6)
def race_data(race_id: str) -> RaceData:
    return RaceData(race_id)


# ── statistics ────────────────────────────────────────────────────────────────

def _fmt_lap(s: float) -> str:
    m, sec = divmod(s, 60)
    return f"{int(m)}:{sec:06.3f}"


def _pit_loss_estimates(rd: RaceData) -> dict[str, list[float]]:
    """
    Rough time lost per stop: (in-lap + out-lap) minus two laps at the
    driver's own clean pace. An estimate, not a timed pit-lane figure —
    stops under a neutralisation are skipped because the field is slow then.
    """
    out: dict[str, list[float]] = {}
    neutral = set(rd.neutral_laps)
    for drv, stops in rd.pit_laps.items():
        own = rd.clean[rd.clean["Driver"] == drv]["LapTime_s"]
        if len(own) < 5:
            continue
        pace = float(own.median())
        g = rd.laps[rd.laps["Driver"] == drv].set_index("LapNumber")["LapTime_s"]
        for lap in stops:
            if lap in neutral or (lap + 1) in neutral:
                continue
            if lap in g.index and (lap + 1) in g.index and pd.notna(g[lap]) and pd.notna(g[lap + 1]):
                loss = float(g[lap] + g[lap + 1] - 2 * pace)
                if 5 <= loss <= 60:
                    out.setdefault(drv, []).append(loss)
    return out


def summary(race_id: str) -> dict:
    rd = race_data(race_id)
    laps = rd.laps

    # fastest lap of the race (any lap with a time)
    timed = laps[laps["LapTime_s"].notna()]
    fl = timed.loc[timed["LapTime_s"].idxmin()]

    # lead changes: who is P1 each lap
    leaders = rd.rank_by_lap.idxmin(axis=1)
    lead_changes = int((leaders != leaders.shift()).sum() - 1) if len(leaders) else 0
    distinct_leaders = list(dict.fromkeys(leaders.tolist()))

    per_driver = rd.clean.groupby("Driver")
    best = timed.groupby("Driver")["LapTime_s"].min()
    median_pace = per_driver["LapTime_s"].median()
    consistency = per_driver["rel_delta"].std()
    n_clean = per_driver["LapTime_s"].count()
    stops = {d: len(v) for d, v in rd.pit_laps.items()}
    losses = _pit_loss_estimates(rd)
    all_losses = [x for v in losses.values() for x in v]

    start_rank = rd.rank_by_lap.iloc[0] if len(rd.rank_by_lap) else pd.Series(dtype=float)
    gained = {
        d: int(start_rank[d] - rd.position[d])
        for d in rd.finishers
        if d in start_rank.index and pd.notna(start_rank[d])
    }

    eligible = [d for d in n_clean.index if n_clean[d] >= 15 and pd.notna(consistency.get(d))]
    most_consistent = min(eligible, key=lambda d: consistency[d]) if eligible else None
    fastest_pace = median_pace.idxmin() if len(median_pace) else None

    comp_share = laps["Compound"].value_counts(normalize=True)
    top_comp = comp_share.index[0] if len(comp_share) else None

    winner = rd.cars[0]
    cards = [
        {"label": "Winner", "value": winner.driver_code, "sub": winner.team},
        {"label": "Fastest lap", "value": _fmt_lap(float(fl["LapTime_s"])),
         "sub": f"{fl['Driver']} · lap {int(fl['LapNumber'])} · {fl['Compound'].title()}"},
        {"label": "Finishers / DNF", "value": f"{len(rd.finishers)} / {len(rd.cars) - len(rd.finishers)}",
         "sub": f"{len(rd.cars)} starters"},
        {"label": "Lead changes", "value": str(lead_changes),
         "sub": " → ".join(distinct_leaders[:4]) + ("…" if len(distinct_leaders) > 4 else "")},
        {"label": "Neutralised laps", "value": str(len(rd.neutral_laps)),
         "sub": "safety car / VSC / red flag" if rd.neutral_laps else "none detected"},
        {"label": "Pit stops", "value": str(sum(stops.values())),
         "sub": f"{sum(stops.get(d, 0) for d in rd.finishers) / max(len(rd.finishers), 1):.1f} per finisher"},
    ]
    if all_losses:
        cards.append({"label": "Median stop loss", "value": f"{np.median(all_losses):.1f}s",
                      "sub": f"estimated, {len(all_losses)} green-flag stops"})
    if gained:
        up = max(gained, key=gained.get)
        down = min(gained, key=gained.get)
        if gained[up] > 0:
            cards.append({"label": "Most places gained", "value": f"{up} +{gained[up]}", "sub": "vs. position after lap 1"})
        if gained[down] < 0:
            cards.append({"label": "Most places lost", "value": f"{down} {gained[down]:+d}", "sub": "vs. position after lap 1"})
    if fastest_pace is not None:
        cards.append({"label": "Best race pace", "value": fastest_pace,
                      "sub": f"median clean lap {_fmt_lap(float(median_pace[fastest_pace]))}"})
    if most_consistent is not None:
        cards.append({"label": "Most consistent", "value": most_consistent,
                      "sub": f"±{consistency[most_consistent]:.2f}s vs. field"})
    if top_comp:
        cards.append({"label": "Most-used tyre", "value": top_comp.title(),
                      "sub": f"{comp_share.iloc[0] * 100:.0f}% of all laps"})

    table = []
    fastest_time = float(fl["LapTime_s"])
    for c in rd.cars:
        d = c.driver_code
        table.append({
            "position": c.position, "driver_code": d, "team": c.team,
            "status": "DNF" if c.retired else (f"+{c.laps_down} LAP" if c.laps_down else "Finished"),
            "best_lap": _fmt_lap(float(best[d])) if d in best.index else None,
            "is_fastest": bool(d in best.index and abs(float(best[d]) - fastest_time) < 1e-6),
            "median_pace": _fmt_lap(float(median_pace[d])) if d in median_pace.index else None,
            "consistency": round(float(consistency[d]), 3) if d in consistency.index and pd.notna(consistency[d]) else None,
            "stops": stops.get(d, 0),
            "places_gained": gained.get(d),
            "color": team_color(c.team),
        })

    return {
        "race_id": race_id,
        "event_name": rd.meta.get("event_name"),
        "year": rd.meta.get("year"),
        "circuit": rd.meta.get("circuit"),
        "total_laps": rd.total_laps,
        "neutral_laps": rd.neutral_laps,
        "cards": cards,
        "drivers": table,
    }


# ── chart plumbing ────────────────────────────────────────────────────────────

def _new_fig(w: float = 10.5, h: float = 5.2) -> tuple[Figure, "Axes"]:
    fig = Figure(figsize=(w, h), dpi=120, facecolor=BG)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    _style_ax(ax)
    return fig, ax


def _style_ax(ax) -> None:
    ax.set_facecolor(BG)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)


def _png(fig: Figure, tight: bool = True) -> bytes:
    buf = io.BytesIO()
    if tight:
        fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=BG)
    return buf.getvalue()


def _shade_neutral(ax, rd: RaceData) -> None:
    for lap in rd.neutral_laps:
        ax.axvspan(lap - 0.5, lap + 0.5, color="#f59e0b", alpha=0.12, linewidth=0)


def _empty(message: str) -> bytes:
    fig, ax = _new_fig(10.5, 3)
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=MUTED, fontsize=11)
    return _png(fig)


# ── charts ────────────────────────────────────────────────────────────────────

def chart_race_trace(rd: RaceData) -> bytes:
    fig, ax = _new_fig(10.5, 6.2)
    _shade_neutral(ax, rd)
    n = len(rd.order)
    for drv in rd.order:
        if drv not in rd.rank_by_lap.columns:
            continue
        s = rd.rank_by_lap[drv].dropna()
        if s.empty:
            continue
        st = rd.style(drv)
        ax.plot(s.index, s.values, color=st["color"], linestyle=st["linestyle"], linewidth=1.5, alpha=0.95)
        # hollow markers on the laps a driver came into the pits
        pits = [l for l in rd.pit_laps.get(drv, []) if l in s.index]
        if pits:
            ax.scatter(pits, s.loc[pits].values, s=22, facecolors=BG, edgecolors=st["color"], linewidths=1.2, zorder=3)
        ax.text(s.index[-1] + 0.6, s.values[-1], drv, color=st["color"], fontsize=7.5, va="center", fontweight="bold")
    ax.set_ylim(n + 0.6, 0.4)
    ax.set_yticks(range(1, n + 1, 1 if n <= 12 else 2))
    ax.set_xlim(0.5, rd.total_laps + 4)
    ax.set_xlabel("Lap")
    ax.set_ylabel("Position")
    ax.set_title("Race trace — position by lap  (○ = pit stop, shaded = neutralised)", color=FG, fontsize=11, loc="left")
    return _png(fig)


def chart_lap_times(rd: RaceData) -> bytes:
    fig, ax = _new_fig(10.5, 5.4)
    _shade_neutral(ax, rd)
    top = [d for d in rd.order if d in rd.finishers][:10]
    vals = []
    for drv in top:
        s = rd.clean[rd.clean["Driver"] == drv].set_index("LapNumber")["LapTime_s"].sort_index()
        if s.empty:
            continue
        # reindex to every lap so removed laps (pit, neutralised) leave a gap
        # in the line instead of being joined by a misleading straight segment
        s = s.reindex(range(1, rd.total_laps + 1))
        st = rd.style(drv)
        ax.plot(s.index, s.values, color=st["color"], linestyle=st["linestyle"], linewidth=1.2, alpha=0.9, label=drv)
        vals.extend(s.dropna().values.tolist())
    if vals:
        lo, hi = np.percentile(vals, [0.5, 99.5])
        ax.set_ylim(lo - 0.4, hi + 0.4)
    ax.set_xlabel("Lap")
    ax.set_ylabel("Lap time (s)")
    ax.set_title("Lap times — top 10 finishers, clean racing laps only", color=FG, fontsize=11, loc="left")
    leg = ax.legend(ncol=5, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    for t in leg.get_texts():
        t.set_color(FG)
    return _png(fig)


def chart_pace_box(rd: RaceData) -> bytes:
    groups = {d: g["LapTime_s"].values for d, g in rd.clean.groupby("Driver") if len(g) >= 8}
    if not groups:
        return _empty("Not enough clean laps for a pace distribution")
    order = sorted(groups, key=lambda d: np.median(groups[d]))
    fig, ax = _new_fig(10.5, max(4.5, 0.28 * len(order) + 1.6))
    bp = ax.boxplot([groups[d] for d in order], vert=False, patch_artist=True, showfliers=False,
                    widths=0.62, medianprops={"color": "#ffffff", "linewidth": 1.4},
                    whiskerprops={"color": MUTED}, capprops={"color": MUTED})
    for patch, d in zip(bp["boxes"], order):
        patch.set_facecolor(team_color(rd.team.get(d, "")))
        patch.set_alpha(0.85)
        patch.set_edgecolor(BG)
    ax.set_yticks(range(1, len(order) + 1))
    ax.set_yticklabels(order, color=FG, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Lap time (s)")
    ax.set_title("Race pace distribution — clean laps, fastest median at top", color=FG, fontsize=11, loc="left")
    return _png(fig)


def chart_tyre_deg(rd: RaceData) -> bytes:
    df = rd.clean[(rd.clean["TyreLife"] > 0) & (rd.clean["TyreLife"] <= 40)]
    fig, ax = _new_fig(10.5, 5.2)
    plotted = False
    for comp in ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"):
        g = df[df["Compound"] == comp]
        if len(g) < 25:
            continue
        col = COMPOUND_COLORS[comp]
        ax.scatter(g["TyreLife"], g["rel_delta"].clip(-3, 3), s=6, color=col, alpha=0.12, linewidths=0)
        # 3-lap buckets: single-lap means are too noisy to read a trend from
        g = g.assign(bucket=(g["TyreLife"] // 3) * 3 + 1)
        m = g.groupby("bucket")["rel_delta"].agg(["mean", "count"])
        m = m[m["count"] >= 8]
        if len(m) >= 3:
            ax.plot(m.index, m["mean"], color=col, linewidth=2.2, marker="o", markersize=3.5, label=f"{comp.title()}  (n={len(g)})")
            plotted = True
    if not plotted:
        return _empty("Not enough laps on any compound for a tyre-age view")
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.set_ylim(-1.8, 1.8)
    ax.set_xlabel("Tyre age (laps)")
    ax.set_ylabel("Pace vs. field, same lap (s)")
    ax.set_title("Pace vs. tyre age — relative to the field on the same lap, per-driver offset removed",
                 color=FG, fontsize=11, loc="left")
    leg = ax.legend(fontsize=8, frameon=False, loc="upper left")
    for t in leg.get_texts():
        t.set_color(FG)
    return _png(fig)


def chart_gap_heatmap(rd: RaceData) -> bytes:
    order = [d for d in rd.order if d in rd.gap_by_lap.columns]
    grid = rd.gap_by_lap[order].T          # drivers × laps
    data = np.ma.masked_invalid(grid.values.astype(float))
    fig, ax = _new_fig(10.5, max(4.5, 0.27 * len(order) + 1.8))
    ax.grid(False)
    cmap = __import__("matplotlib").colormaps["plasma_r"].copy()
    cmap.set_bad(BG)
    vmax = 90
    im = ax.imshow(data, aspect="auto", cmap=cmap, vmin=0, vmax=vmax,
                   extent=(grid.columns.min() - 0.5, grid.columns.max() + 0.5, len(order) - 0.5, -0.5),
                   interpolation="nearest")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, color=FG, fontsize=8)
    ax.set_xlabel("Lap")
    ax.set_title(f"Gap to leader by lap (s, capped at {vmax}) — blank = not running", color=FG, fontsize=11, loc="left")
    cb = fig.colorbar(im, ax=ax, pad=0.01, fraction=0.03)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.outline.set_edgecolor(GRID)
    return _png(fig)


def chart_pit_stops(rd: RaceData) -> bytes:
    order = [d for d in rd.order]
    fig = Figure(figsize=(10.5, max(4.8, 0.3 * len(order) + 1.8)), dpi=120, facecolor=BG)
    FigureCanvasAgg(fig)
    gs = fig.add_gridspec(1, 2, width_ratios=[3, 1], wspace=0.05)
    ax = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharey=ax)
    _style_ax(ax)
    _style_ax(ax2)

    comp_after: dict[tuple[str, int], str] = {
        (r.Driver, int(r.LapNumber)): r.Compound for r in rd.laps.itertuples()
    }
    _shade_neutral(ax, rd)
    for i, drv in enumerate(order):
        for lap in rd.pit_laps.get(drv, []):
            comp = comp_after.get((drv, lap + 1), "UNKNOWN")
            ax.scatter(lap, i, s=70, color=COMPOUND_COLORS.get(comp, "#6b7280"), edgecolors=BG, linewidths=1, zorder=3)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order, color=FG, fontsize=8)
    ax.set_ylim(len(order) - 0.5, -0.5)
    ax.set_xlim(0, rd.total_laps + 1)
    ax.set_xlabel("Lap of stop  (colour = tyre fitted)")
    ax.set_title("Pit stops", color=FG, fontsize=11, loc="left")

    losses = _pit_loss_estimates(rd)
    for i, drv in enumerate(order):
        if drv in losses:
            ax2.barh(i, float(np.median(losses[drv])), color=team_color(rd.team.get(drv, "")), alpha=0.85, height=0.6)
    ax2.set_xlabel("Est. loss / stop (s)")
    ax2.tick_params(labelleft=False)
    handles = [__import__("matplotlib").lines.Line2D([], [], marker="o", linestyle="", color=c, label=n.title(), markersize=7)
               for n, c in COMPOUND_COLORS.items() if n in ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET")]
    leg = ax.legend(handles=handles, ncol=5, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09))
    for t in leg.get_texts():
        t.set_color(FG)
    fig.subplots_adjust(left=0.07, right=0.985, top=0.94, bottom=0.15)
    return _png(fig, tight=False)


def chart_positions_gained(rd: RaceData) -> bytes:
    start = rd.rank_by_lap.iloc[0]
    rows = [(d, int(start[d] - rd.position[d])) for d in rd.finishers if d in start.index and pd.notna(start[d])]
    if not rows:
        return _empty("No position data")
    rows.sort(key=lambda r: r[1])
    fig, ax = _new_fig(10.5, max(4.5, 0.28 * len(rows) + 1.5))
    names = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    ax.barh(range(len(rows)), vals, color=["#22c55e" if v > 0 else "#ef4444" if v < 0 else "#6b7280" for v in vals], height=0.65)
    for i, v in enumerate(vals):
        ax.text(v + (0.15 if v >= 0 else -0.15), i, f"{v:+d}", va="center", ha="left" if v >= 0 else "right", color=FG, fontsize=8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(names, color=FG, fontsize=8)
    ax.axvline(0, color=MUTED, linewidth=0.8)
    ax.set_xlabel("Places gained (+) / lost (−)")
    ax.set_title("Positions gained since lap 1 — finishers", color=FG, fontsize=11, loc="left")
    return _png(fig)


def chart_consistency(rd: RaceData) -> bytes:
    g = rd.clean.groupby("Driver")["rel_delta"].agg(["std", "count"])
    g = g[(g["count"] >= 15) & g["std"].notna()].sort_values("std")
    if g.empty:
        return _empty("Not enough clean laps to rank consistency")
    fig, ax = _new_fig(10.5, max(4.5, 0.28 * len(g) + 1.5))
    ax.barh(range(len(g)), g["std"].values, color=[team_color(rd.team.get(d, "")) for d in g.index], height=0.65, alpha=0.9)
    for i, v in enumerate(g["std"].values):
        ax.text(v + 0.01, i, f"{v:.2f}s", va="center", color=FG, fontsize=8)
    ax.set_yticks(range(len(g)))
    ax.set_yticklabels(g.index, color=FG, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Lap-time spread vs. field (s, std-dev — lower is steadier)")
    ax.set_title("Consistency — most consistent at top", color=FG, fontsize=11, loc="left")
    return _png(fig)


# id → (title, caption, renderer)
CHARTS: dict[str, tuple[str, str, Callable[[RaceData], bytes]]] = {
    "race_trace": ("Race trace", "Position on every lap. Hollow dots are pit stops; amber bands are neutralised laps.", chart_race_trace),
    "lap_times": ("Lap times", "Clean racing laps for the top ten finishers (pit laps and neutralised laps removed).", chart_lap_times),
    "pace_box": ("Pace distribution", "Spread of each driver's clean laps. White line = median; box = middle 50%.", chart_pace_box),
    "gap_heatmap": ("Gap to leader", "How far each car was from the lead on every lap. Colour is capped so the fight near the front stays readable.", chart_gap_heatmap),
    "pit_stops": ("Pit stops", "When each driver stopped and what they fitted, with an estimated time loss per stop (in-lap + out-lap vs. own pace).", chart_pit_stops),
    "tyre_deg": ("Tyre age vs. pace", "Pace against the field on the same lap, so fuel burn and track evolution cancel out. Indicative — tyre age and race phase overlap.", chart_tyre_deg),
    "positions_gained": ("Places gained", "Finishing position compared with position after the opening lap.", chart_positions_gained),
    "consistency": ("Consistency", "Lap-to-lap spread relative to the field — a steadier driver has a smaller bar.", chart_consistency),
}


def chart_list() -> list[dict]:
    return [{"id": cid, "title": t, "caption": cap} for cid, (t, cap, _) in CHARTS.items()]


def _chart_path(race_id: str, chart_id: str) -> Path:
    return Path(settings.cache_dir) / "processed" / "charts" / f"{race_id}_{chart_id}_v{ANALYTICS_VERSION}.png"


def render_chart(race_id: str, chart_id: str) -> Optional[bytes]:
    """PNG bytes for one chart, cached on disk (rebuilt if the race data is newer)."""
    if chart_id not in CHARTS:
        return None
    path = _chart_path(race_id, chart_id)
    from app.engine import storage
    source = storage._path(race_id)
    if path.exists() and (not source.exists() or path.stat().st_mtime >= source.stat().st_mtime):
        return path.read_bytes()
    png = CHARTS[chart_id][2](race_data(race_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return png
