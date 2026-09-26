"""
Race and season insights — a wide catalogue of small, named statistics
computed from the persistently-cached lap DataFrame (the same data every
other analytic in this app already reads; no extra data source is touched).

Each race yields ~40 insights in five groups (Pace, Consistency, Strategy,
Tyres, Race flow) plus a compact "facts" dict that the season roll-ups and
the retrieval index (rag.py) are built from.

Method notes, because several of these are estimates rather than timing
data the FIA publishes:

* "Clean" laps are the ones analytics.RaceData already defines: timed, not a
  pit in/out lap, not neutralised (safety car / VSC / red flag) and not the
  lap either side of one.
* Position swaps compare the order in which cars complete consecutive laps.
  Pit-affected laps and neutralised laps are skipped, so pit-cycle shuffles
  and restarts aren't counted as overtakes. It is still an estimate.
* Undercut success looks at a car that pitted while the car directly ahead
  stayed out, and checks who was ahead once the car ahead had also stopped.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from app.core.config import settings
from app.engine.analytics import RaceData, race_data, _fmt_lap, _pit_loss_estimates

log = logging.getLogger(__name__)

# Bump when an insight's meaning changes so cached JSON is rebuilt.
INSIGHTS_VERSION = 2

CATEGORIES = ["Pace", "Consistency", "Strategy", "Tyres", "Race flow"]
_LETTER = {"SOFT": "S", "MEDIUM": "M", "HARD": "H", "INTERMEDIATE": "I", "WET": "W", "UNKNOWN": "?"}


# ── small helpers ─────────────────────────────────────────────────────────────

def _ranges(laps: list[int]) -> str:
    """[3,4,5,9] → '3–5, 9'."""
    laps = sorted(laps)
    out, start, prev = [], None, None
    for l in laps:
        if start is None:
            start = prev = l
        elif l == prev + 1:
            prev = l
        else:
            out.append((start, prev))
            start = prev = l
    if start is not None:
        out.append((start, prev))
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in out)


def _dedupe_stops(laps: list[int]) -> list[int]:
    """
    Collapse runs of consecutive pit-in laps into one stop. Under a red flag
    (or when a car sits in the pit lane across the timing line) the feed marks
    the same visit on two laps in a row, which would otherwise double-count.
    """
    out: list[int] = []
    prev = None
    for l in sorted(laps):
        if prev is None or l != prev + 1:
            out.append(l)
        prev = l
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _ins(cid: str, cat: str, title: str, value, detail: str = "") -> dict:
    return {"id": cid, "category": cat, "title": title, "value": str(value), "detail": detail}


class _Ctx:
    """Shared intermediate results so each insight stays a few lines long."""

    def __init__(self, rd: RaceData):
        self.rd = rd
        laps = rd.laps
        self.timed = laps[laps["LapTime_s"].notna()]
        self.median_pace = rd.clean.groupby("Driver")["LapTime_s"].median()
        self.n_clean = rd.clean.groupby("Driver")["LapTime_s"].count()
        self.consistency = rd.clean.groupby("Driver")["rel_delta"].std()
        self.eligible = [d for d in self.n_clean.index
                         if self.n_clean[d] >= 15 and pd.notna(self.consistency.get(d))]
        self.pit_laps = {d: _dedupe_stops(v) for d, v in rd.pit_laps.items()}
        self.stints = self._stints()
        self.swaps, self.swap_pairs = self._swaps()
        self.undercut_attempts, self.undercut_wins = self._undercuts()
        self.pit_losses = _pit_loss_estimates(rd)
        self.winner = rd.cars[0]
        self.finisher_set = set(rd.finishers)

    def _stints(self) -> pd.DataFrame:
        df = self.rd.laps.sort_values(["Driver", "LapNumber"]).copy()
        stops = {(d, l) for d, v in self.pit_laps.items() for l in v}
        df["_stop"] = [(d, int(l)) in stops for d, l in zip(df["Driver"], df["LapNumber"])]
        df["stint"] = df.groupby("Driver")["_stop"].transform(
            lambda s: s.shift(fill_value=False).astype(int).cumsum()
        )
        rows = []
        for (drv, st), g in df.groupby(["Driver", "stint"]):
            comp = g["Compound"].mode()
            rows.append({
                "driver": drv, "stint": int(st),
                "compound": comp.iloc[0] if len(comp) else "UNKNOWN",
                "start": int(g["LapNumber"].min()), "end": int(g["LapNumber"].max()),
                "laps": int(len(g)),
            })
        out = pd.DataFrame(rows, columns=["driver", "stint", "compound", "start", "end", "laps"])
        if len(out):
            out["final"] = out.groupby("driver")["stint"].transform("max") == out["stint"]
        else:
            out["final"] = pd.Series(dtype=bool)
        return out

    def _swaps(self) -> tuple[int, Counter]:
        rd = self.rd
        T = rd.time_by_lap
        if T.empty:
            return 0, Counter()
        cols = list(T.columns)
        arr = T.to_numpy(dtype=float)
        lap_idx = {int(l): i for i, l in enumerate(T.index)}
        pit = {(r.Driver, int(r.LapNumber)) for r in rd.laps.itertuples() if r.IsPitIn or r.IsPitOut}
        neutral = set(rd.neutral_laps)
        edges = neutral | {l - 1 for l in neutral} | {l + 1 for l in neutral}
        pairs: Counter = Counter()
        for l in sorted(lap_idx):
            p = l - 1
            if p not in lap_idx or l in edges or p in edges:
                continue
            ip, il = lap_idx[p], lap_idx[l]
            ok = [j for j, d in enumerate(cols)
                  if not np.isnan(arr[ip, j]) and not np.isnan(arr[il, j])
                  and (d, p) not in pit and (d, l) not in pit]
            for x in range(len(ok)):
                for y in range(x + 1, len(ok)):
                    a, b = ok[x], ok[y]
                    if (arr[ip, a] < arr[ip, b]) != (arr[il, a] < arr[il, b]):
                        pairs[frozenset((cols[a], cols[b]))] += 1
        return int(sum(pairs.values())), pairs

    def _undercuts(self) -> tuple[int, int]:
        rd = self.rd
        rank = rd.rank_by_lap
        neutral = set(rd.neutral_laps)
        attempts = wins = 0
        for a, stops in self.pit_laps.items():
            if a not in rank.columns:
                continue
            for L in stops:
                if L in neutral or (L - 1) not in rank.index:
                    continue
                ra = rank.at[L - 1, a]
                if pd.isna(ra):
                    continue
                row = rank.loc[L - 1]
                ahead = row[row == ra - 1]
                if ahead.empty:
                    continue
                b = ahead.index[0]
                later = [s for s in self.pit_laps.get(b, []) if L < s <= L + 6]
                if not later or (later[0] + 1) not in rank.index:
                    continue
                ra2, rb2 = rank.at[later[0] + 1, a], rank.at[later[0] + 1, b]
                if pd.isna(ra2) or pd.isna(rb2):
                    continue
                attempts += 1
                wins += int(ra2 < rb2)
        return attempts, wins


# ── insights ──────────────────────────────────────────────────────────────────
# Each takes a _Ctx and returns an insight dict, or None when the race doesn't
# have the data to support it (they're skipped rather than shown as blanks).

def _fastest_lap(c: _Ctx):
    fl = c.timed.loc[c.timed["LapTime_s"].idxmin()]
    return _ins("fastest_lap", "Pace", "Fastest lap", f"{fl['Driver']} {_fmt_lap(float(fl['LapTime_s']))}",
                f"Lap {int(fl['LapNumber'])} on {fl['Compound'].title()} tyres.")


def _fastest_lap_timing(c: _Ctx):
    fl = c.timed.loc[c.timed["LapTime_s"].idxmin()]
    pct = 100 * int(fl["LapNumber"]) / c.rd.total_laps
    late = pct >= 85
    return _ins("fastest_lap_timing", "Pace", "Fastest lap came", f"{pct:.0f}% through the race",
                "A late fastest lap usually means a fresh-tyre end-of-race push." if late
                else "Set mid-race, on a lighter fuel load / strong stint rather than a late push.")


def _fastest_pace(c: _Ctx):
    ok = [d for d in c.eligible]
    if not ok:
        return None
    d = min(ok, key=lambda x: c.median_pace[x])
    return _ins("fastest_pace", "Pace", "Best race pace", d, f"Median clean lap {_fmt_lap(float(c.median_pace[d]))}.")


def _slowest_pace(c: _Ctx):
    ok = [d for d in c.eligible]
    if len(ok) < 3:
        return None
    d = max(ok, key=lambda x: c.median_pace[x])
    return _ins("slowest_pace", "Pace", "Slowest race pace", d, f"Median clean lap {_fmt_lap(float(c.median_pace[d]))}.")


def _field_spread(c: _Ctx):
    ok = c.eligible
    if len(ok) < 4:
        return None
    vals = [c.median_pace[d] for d in ok]
    return _ins("field_spread", "Pace", "Fastest-to-slowest pace gap", f"{max(vals) - min(vals):.2f}s",
                f"Difference between the best and worst median clean lap among {len(ok)} drivers.")


def _winner_pace_gap(c: _Ctx):
    w = c.winner.driver_code
    others = [d for d in c.rd.order[1:] if d in c.eligible]
    if w not in c.eligible or not others:
        return None
    r = others[0]
    gap = float(c.median_pace[r] - c.median_pace[w])
    return _ins("winner_pace_gap", "Pace", "Winner vs runner-up pace", f"{gap:+.2f}s/lap",
                f"{w}'s median clean lap vs {r}'s ({'winner faster' if gap > 0 else 'runner-up faster'}).")


def _best_team_pace(c: _Ctx):
    g = c.rd.clean.groupby("Team")["field_delta"].agg(["median", "count"])
    g = g[g["count"] >= 30].sort_values("median")
    if len(g) < 3:
        return None
    return _ins("best_team_pace", "Pace", "Fastest team on pace", g.index[0],
                f"{g['median'].iloc[0]:+.2f}s vs the field's median lap, same-lap comparison.")


def _worst_team_pace(c: _Ctx):
    g = c.rd.clean.groupby("Team")["field_delta"].agg(["median", "count"])
    g = g[g["count"] >= 30].sort_values("median")
    if len(g) < 3:
        return None
    return _ins("worst_team_pace", "Pace", "Slowest team on pace", g.index[-1],
                f"{g['median'].iloc[-1]:+.2f}s vs the field's median lap, same-lap comparison.")


def _field_evolution(c: _Ctx):
    cl = c.rd.clean
    if len(cl) < 60:
        return None
    lo, hi = cl["LapNumber"].quantile([1 / 3, 2 / 3])
    early = cl[cl["LapNumber"] <= lo]["LapTime_s"].median()
    late = cl[cl["LapNumber"] >= hi]["LapTime_s"].median()
    d = float(late - early)
    return _ins("field_evolution", "Pace", "Pace change, first vs last third", f"{d:+.2f}s",
                "Negative = the field got faster (fuel burn and a rubbered-in track outweigh tyre wear).")


def _fl_vs_typical(c: _Ctx):
    if c.rd.clean.empty:
        return None
    fl = float(c.timed["LapTime_s"].min())
    typ = float(c.rd.clean["LapTime_s"].median())
    return _ins("fl_vs_typical", "Pace", "Fastest lap vs typical lap", f"{typ - fl:.2f}s quicker",
                f"Fastest lap {_fmt_lap(fl)} against a median clean racing lap of {_fmt_lap(typ)}.")


def _most_consistent(c: _Ctx):
    if not c.eligible:
        return None
    d = min(c.eligible, key=lambda x: c.consistency[x])
    return _ins("most_consistent", "Consistency", "Most consistent driver", d,
                f"±{c.consistency[d]:.2f}s lap-to-lap spread vs the field.")


def _least_consistent(c: _Ctx):
    if len(c.eligible) < 4:
        return None
    d = max(c.eligible, key=lambda x: c.consistency[x])
    return _ins("least_consistent", "Consistency", "Least consistent driver", d,
                f"±{c.consistency[d]:.2f}s lap-to-lap spread vs the field.")


def _consistent_team(c: _Ctx):
    rows = {}
    for d in c.eligible:
        rows.setdefault(c.rd.team.get(d, ""), []).append(float(c.consistency[d]))
    rows = {t: np.mean(v) for t, v in rows.items() if t}
    if len(rows) < 3:
        return None
    t = min(rows, key=rows.get)
    return _ins("consistent_team", "Consistency", "Most consistent team", t, f"Average spread ±{rows[t]:.2f}s across its drivers.")


def _peak_laps(c: _Ctx):
    best_d, best_n = None, -1
    for d in c.eligible:
        s = c.rd.clean[c.rd.clean["Driver"] == d]["LapTime_s"]
        n = int((s <= s.min() + 0.5).sum())
        if n > best_n:
            best_d, best_n = d, n
    if best_d is None:
        return None
    return _ins("peak_laps", "Consistency", "Most laps near own best", f"{best_d} ({best_n})",
                "Clean laps within 0.5s of that driver's own best clean lap.")


def _tight_field(c: _Ctx):
    ok = c.eligible
    if len(ok) < 6:
        return None
    devs = np.array([c.consistency[d] for d in ok])
    return _ins("tight_field", "Consistency", "Median lap-to-lap spread", f"±{np.median(devs):.2f}s",
                "Typical consistency across the field; higher means a more mixed, traffic- or tyre-affected race.")


def _total_stops(c: _Ctx):
    n = sum(len(v) for v in c.pit_laps.values())
    return _ins("total_stops", "Strategy", "Total pit stops", n, f"Across {len(c.rd.cars)} cars.")


def _avg_stops(c: _Ctx):
    fin = c.rd.finishers
    if not fin:
        return None
    avg = sum(len(c.pit_laps.get(d, [])) for d in fin) / len(fin)
    return _ins("avg_stops", "Strategy", "Average stops per finisher", f"{avg:.2f}")


def _strategy_of(c: _Ctx, drv: str) -> str:
    s = c.stints[c.stints["driver"] == drv].sort_values("stint")
    return "-".join(_LETTER.get(x, "?") for x in s["compound"])


def _common_strategy(c: _Ctx):
    strategies = [_strategy_of(c, d) for d in c.rd.finishers]
    strategies = [s for s in strategies if s]
    if not strategies:
        return None
    top, n = Counter(strategies).most_common(1)[0]
    return _ins("common_strategy", "Strategy", "Most common strategy", top,
                f"Used by {n} of {len(strategies)} finishers (S=soft, M=medium, H=hard, I=inter, W=wet).")


def _n_strategies(c: _Ctx):
    strategies = {_strategy_of(c, d) for d in c.rd.finishers} - {""}
    if not strategies:
        return None
    return _ins("n_strategies", "Strategy", "Distinct strategies", len(strategies), "Different compound sequences among the finishers.")


def _winner_strategy(c: _Ctx):
    s = _strategy_of(c, c.winner.driver_code)
    if not s:
        return None
    stops = len(c.pit_laps.get(c.winner.driver_code, []))
    return _ins("winner_strategy", "Strategy", "Winner's strategy", s, f"{c.winner.driver_code}: {_plural(stops, 'stop')}.")


def _longest_stint(c: _Ctx):
    s = c.stints
    if s.empty:
        return None
    r = s.loc[s["laps"].idxmax()]
    return _ins("longest_stint", "Strategy", "Longest stint", f"{r['driver']} · {_plural(int(r['laps']), 'lap')}",
                f"On {r['compound'].title()} tyres, laps {int(r['start'])}–{int(r['end'])}.")


def _shortest_stint(c: _Ctx):
    s = c.stints[~c.stints["final"]]
    if s.empty:
        return None
    r = s.loc[s["laps"].idxmin()]
    return _ins("shortest_stint", "Strategy", "Shortest stint", f"{r['driver']} · {_plural(int(r['laps']), 'lap')}",
                f"On {r['compound'].title()} tyres before pitting, laps {int(r['start'])}–{int(r['end'])}.")


def _first_stop_early(c: _Ctx):
    firsts = {d: v[0] for d, v in c.pit_laps.items() if v}
    if not firsts:
        return None
    d = min(firsts, key=firsts.get)
    return _ins("first_stop_early", "Strategy", "Earliest first stop", f"{d} · lap {firsts[d]}")


def _first_stop_late(c: _Ctx):
    firsts = {d: v[0] for d, v in c.pit_laps.items() if v}
    if not firsts:
        return None
    d = max(firsts, key=firsts.get)
    return _ins("first_stop_late", "Strategy", "Latest first stop", f"{d} · lap {firsts[d]}")


def _undercut_rate(c: _Ctx):
    if c.undercut_attempts < 2:
        return None
    return _ins("undercut_rate", "Strategy", "Undercut success rate",
                f"{c.undercut_wins}/{c.undercut_attempts}",
                "Stops made just before the car ahead pitched, that ended up leading it. An estimate from lap order.")


def _median_pit_loss(c: _Ctx):
    allv = [x for v in c.pit_losses.values() for x in v]
    if not allv:
        return None
    return _ins("median_pit_loss", "Strategy", "Median time lost per stop", f"{np.median(allv):.1f}s",
                f"Estimated from in-lap + out-lap vs own pace, {len(allv)} green-flag stops.")


def _best_pit_team(c: _Ctx):
    by_team: dict[str, list[float]] = {}
    for d, v in c.pit_losses.items():
        by_team.setdefault(c.rd.team.get(d, ""), []).extend(v)
    by_team = {t: np.median(v) for t, v in by_team.items() if t and len(v) >= 2}
    if len(by_team) < 3:
        return None
    t = min(by_team, key=by_team.get)
    return _ins("best_pit_team", "Strategy", "Quickest pit-cycle team", t, f"Median estimated loss {by_team[t]:.1f}s per stop.")


def _compound_share(c: _Ctx):
    share = c.rd.laps["Compound"].value_counts(normalize=True)
    share = share[share.index != "UNKNOWN"]
    if share.empty:
        return None
    txt = " / ".join(f"{k.title()} {v * 100:.0f}%" for k, v in share.items())
    return _ins("compound_share", "Tyres", "Tyre mix (share of laps)", share.index[0].title(), txt)


def _n_compounds(c: _Ctx):
    used = set(c.rd.laps["Compound"]) - {"UNKNOWN"}
    if not used:
        return None
    return _ins("n_compounds", "Tyres", "Compounds used", len(used), ", ".join(sorted(x.title() for x in used)))


def _deg_rates(c: _Ctx):
    df = c.rd.clean[(c.rd.clean["TyreLife"] > 0) & (c.rd.clean["TyreLife"] <= 40)]
    rates = {}
    for comp, g in df.groupby("Compound"):
        if comp == "UNKNOWN" or len(g) < 40 or g["TyreLife"].nunique() < 6:
            continue
        slope = float(np.polyfit(g["TyreLife"], g["rel_delta"].clip(-3, 3), 1)[0])
        rates[comp] = slope
    if not rates:
        return None
    worst = max(rates, key=rates.get)
    txt = " · ".join(f"{k.title()} {v * 1000:+.0f} ms/lap" for k, v in rates.items())
    return _ins("deg_rates", "Tyres", "Tyre degradation rate", f"{worst.title()} fades fastest",
                f"{txt}. Same-lap relative pace vs tyre age; indicative, not a controlled test.")


def _fastest_compound(c: _Ctx):
    g = c.rd.clean[c.rd.clean["Compound"] != "UNKNOWN"].groupby("Compound")["field_delta"].agg(["median", "count"])
    g = g[g["count"] >= 25].sort_values("median")
    if len(g) < 2:
        return None
    return _ins("fastest_compound", "Tyres", "Fastest compound on the day", g.index[0].title(),
                f"{g['median'].iloc[0]:+.2f}s vs the field on the same lap (n={int(g['count'].iloc[0])}).")


def _longest_run(c: _Ctx):
    s = c.stints[c.stints["compound"] != "UNKNOWN"]
    if s.empty:
        return None
    parts = []
    for comp, g in s.groupby("compound"):
        r = g.loc[g["laps"].idxmax()]
        parts.append(f"{comp.title()} {int(r['laps'])} ({r['driver']})")
    return _ins("longest_run", "Tyres", "Longest run per compound", f"{len(parts)} compounds", " · ".join(parts))


def _avg_stint_by_compound(c: _Ctx):
    s = c.stints[(c.stints["compound"] != "UNKNOWN") & (~c.stints["final"])]
    if s.empty:
        return None
    m = s.groupby("compound")["laps"].mean().sort_values(ascending=False)
    return _ins("avg_stint", "Tyres", "Average stint length", f"{m.index[0].title()} lasts longest",
                " · ".join(f"{k.title()} {v:.0f} laps" for k, v in m.items()) + " (stints ended by a stop).")


def _lead_changes(c: _Ctx):
    leaders = c.rd.rank_by_lap.idxmin(axis=1)
    n = int((leaders != leaders.shift()).sum() - 1) if len(leaders) else 0
    order = list(dict.fromkeys(leaders.tolist()))
    return _ins("lead_changes", "Race flow", "Lead changes", n, "Led by: " + " → ".join(order[:6]) + ("…" if len(order) > 6 else ""))


def _laps_led(c: _Ctx):
    leaders = c.rd.rank_by_lap.idxmin(axis=1)
    if leaders.empty:
        return None
    vc = leaders.value_counts()
    return _ins("laps_led", "Race flow", "Most laps led", f"{vc.index[0]} ({int(vc.iloc[0])})",
                f"{len(vc)} different driver{'s' if len(vc) != 1 else ''} led at the end of a lap.")


def _neutral(c: _Ctx):
    n = c.rd.neutral_laps
    return _ins("neutral", "Race flow", "Neutralised laps", len(n),
                f"Laps {_ranges(n)} (safety car / VSC / red flag)." if n else "None detected — a clean green-flag race.")


def _neutral_share(c: _Ctx):
    return _ins("neutral_share", "Race flow", "Share of race under neutralisation",
                f"{100 * len(c.rd.neutral_laps) / max(c.rd.total_laps, 1):.0f}%")


def _swaps(c: _Ctx):
    return _ins("swaps", "Race flow", "On-track position swaps", c.swaps,
                "Estimated overtakes: order changes between consecutive laps, ignoring pit-affected and neutralised laps.")


def _battle(c: _Ctx):
    if not c.swap_pairs:
        return None
    pair, n = c.swap_pairs.most_common(1)[0]
    if n < 2:
        return None
    a, b = sorted(pair)
    return _ins("battle", "Race flow", "Biggest fight", f"{a} vs {b}", f"They swapped order {n} times.")


def _swap_rate(c: _Ctx):
    green = c.rd.total_laps - len(c.rd.neutral_laps)
    if green <= 0:
        return None
    return _ins("swap_rate", "Race flow", "Swaps per green-flag lap", f"{c.swaps / green:.2f}")


def _win_margin(c: _Ctx):
    rd = c.rd
    if len(rd.order) < 2:
        return None
    w, r = rd.order[0], rd.order[1]
    T = rd.time_by_lap
    last = int(rd.laps[rd.laps["Driver"] == w]["LapNumber"].max())
    if last not in T.index or r not in T.columns or pd.isna(T.at[last, r]) or pd.isna(T.at[last, w]):
        return None
    return _ins("win_margin", "Race flow", "Winning margin", f"{float(T.at[last, r] - T.at[last, w]):.3f}s",
                f"{w} over {r}.")


def _closest_finish(c: _Ctx):
    rd = c.rd
    T = rd.time_by_lap
    w = rd.order[0]
    last = int(rd.laps[rd.laps["Driver"] == w]["LapNumber"].max())
    if last not in T.index:
        return None
    fin = [d for d in rd.order if d in T.columns and pd.notna(T.at[last, d])]
    best = None
    for a, b in zip(fin, fin[1:]):
        g = float(T.at[last, b] - T.at[last, a])
        if g >= 0 and (best is None or g < best[0]):
            best = (g, a, b)
    if best is None or len(fin) < 3:
        return None
    return _ins("closest_finish", "Race flow", "Closest finish gap", f"{best[0]:.3f}s", f"{best[1]} ahead of {best[2]} at the flag.")


def _gainer(c: _Ctx):
    rank = c.rd.rank_by_lap
    if rank.empty:
        return None
    start = rank.iloc[0]
    g = {d: int(start[d] - c.rd.position[d]) for d in c.rd.finishers if d in start.index and pd.notna(start[d])}
    if not g:
        return None
    d = max(g, key=g.get)
    if g[d] <= 0:
        return None
    return _ins("gainer", "Race flow", "Most places gained", f"{d} {g[d]:+d}", "Versus running order after lap 1.")


def _loser(c: _Ctx):
    rank = c.rd.rank_by_lap
    if rank.empty:
        return None
    start = rank.iloc[0]
    g = {d: int(start[d] - c.rd.position[d]) for d in c.rd.finishers if d in start.index and pd.notna(start[d])}
    if not g:
        return None
    d = min(g, key=g.get)
    if g[d] >= 0:
        return None
    return _ins("loser", "Race flow", "Most places lost", f"{d} {g[d]:+d}", "Versus running order after lap 1.")


def _dnfs(c: _Ctx):
    n = len(c.rd.cars) - len(c.rd.finishers)
    names = [x.driver_code for x in c.rd.cars if x.retired]
    return _ins("dnfs", "Race flow", "Retirements", n, ", ".join(names) if names else "Everyone was classified.")


def _first_dnf(c: _Ctx):
    rows = []
    for x in c.rd.cars:
        if x.retired:
            last = int(c.rd.laps[c.rd.laps["Driver"] == x.driver_code]["LapNumber"].max())
            rows.append((last, x.driver_code))
    if not rows:
        return None
    lap, d = min(rows)
    return _ins("first_dnf", "Race flow", "First retirement", f"{d} · lap {lap}")


def _lead_lap(c: _Ctx):
    n = sum(1 for x in c.rd.cars if not x.retired and not x.laps_down)
    return _ins("lead_lap", "Race flow", "Finished on the lead lap", n, f"Of {len(c.rd.cars)} starters.")


def _lapped(c: _Ctx):
    n = sum(1 for x in c.rd.cars if not x.retired and x.laps_down)
    return _ins("lapped", "Race flow", "Classified but lapped", n)


INSIGHTS: list[Callable[[_Ctx], Optional[dict]]] = [
    _fastest_lap, _fastest_lap_timing, _fastest_pace, _slowest_pace, _field_spread, _winner_pace_gap,
    _best_team_pace, _worst_team_pace, _field_evolution, _fl_vs_typical,
    _most_consistent, _least_consistent, _consistent_team, _peak_laps, _tight_field,
    _total_stops, _avg_stops, _common_strategy, _n_strategies, _winner_strategy, _longest_stint,
    _shortest_stint, _first_stop_early, _first_stop_late, _undercut_rate, _median_pit_loss, _best_pit_team,
    _compound_share, _n_compounds, _deg_rates, _fastest_compound, _longest_run, _avg_stint_by_compound,
    _lead_changes, _laps_led, _neutral, _neutral_share, _swaps, _battle, _swap_rate, _win_margin,
    _closest_finish, _gainer, _loser, _dnfs, _first_dnf, _lead_lap, _lapped,
]


def _facts(c: _Ctx) -> dict:
    """Machine-readable per-race numbers the season roll-ups are built from."""
    rd = c.rd
    fl = c.timed.loc[c.timed["LapTime_s"].idxmin()]
    leaders = rd.rank_by_lap.idxmin(axis=1)
    allv = [x for v in c.pit_losses.values() for x in v]
    fin = rd.finishers
    strategies = [_strategy_of(c, d) for d in fin]
    return {
        "winner": c.winner.driver_code, "winner_team": c.winner.team,
        "fastest_lap_driver": str(fl["Driver"]), "fastest_lap_s": float(fl["LapTime_s"]),
        "total_laps": int(rd.total_laps),
        "stops": int(sum(len(v) for v in c.pit_laps.values())),
        "starters": len(rd.cars), "finishers": len(fin), "dnfs": len(rd.cars) - len(fin),
        "neutral_laps": len(rd.neutral_laps),
        "lead_changes": int((leaders != leaders.shift()).sum() - 1) if len(leaders) else 0,
        "swaps": c.swaps,
        "median_pit_loss": float(np.median(allv)) if allv else None,
        "top_strategy": Counter(s for s in strategies if s).most_common(1)[0][0] if any(strategies) else None,
        "compound_laps": {k: int(v) for k, v in rd.laps["Compound"].value_counts().items()},
        "podium": [x.driver_code for x in rd.cars[:3]],
    }


def _r(x, n=3):
    return None if x is None or pd.isna(x) else round(float(x), n)


def _extras(c: _Ctx) -> dict:
    """
    Structured data behind the richer visuals (strategy timeline, pace ranking,
    team table, field-pace and tyre-age curves, lead timeline). Plain JSON so
    the frontend can draw it however it likes.
    """
    rd = c.rd
    status = {x.driver_code: ("DNF" if x.retired else (f"+{x.laps_down} LAP" if x.laps_down else "Finished"))
              for x in rd.cars}

    strategy = []
    for x in rd.cars:
        d = x.driver_code
        s_ = c.stints[c.stints["driver"] == d].sort_values("stint")
        strategy.append({
            "driver": d, "team": x.team, "position": x.position, "status": status[d],
            "pit_laps": c.pit_laps.get(d, []),
            "stints": [{"compound": r.compound, "start": int(r.start), "end": int(r.end), "laps": int(r.laps)}
                       for r in s_.itertuples()],
        })

    fastest = min((c.median_pace[d] for d in c.eligible), default=None)
    pace_ranking = sorted(
        ({"driver": d, "team": rd.team.get(d, ""), "median_s": _r(c.median_pace[d]),
          "delta_s": _r(c.median_pace[d] - fastest), "consistency": _r(c.consistency[d]),
          "clean_laps": int(c.n_clean[d])} for d in c.eligible),
        key=lambda r: r["median_s"])

    field = rd.laps[rd.laps["LapTime_s"].notna() & ~rd.laps["IsPitIn"] & ~rd.laps["IsPitOut"]]
    field_pace = [{"lap": int(l), "median_s": _r(v, 2)} for l, v in field.groupby("LapNumber")["LapTime_s"].median().items()]

    leaders = rd.rank_by_lap.idxmin(axis=1)
    lead_timeline, cur, start = [], None, None
    for lap, drv in leaders.items():
        if drv != cur:
            if cur is not None:
                lead_timeline.append({"driver": cur, "start": int(start), "end": int(prev)})
            cur, start = drv, lap
        prev = lap
    if cur is not None:
        lead_timeline.append({"driver": cur, "start": int(start), "end": int(prev)})

    deg: dict[str, list] = {}
    df = rd.clean[(rd.clean["TyreLife"] > 0) & (rd.clean["TyreLife"] <= 40) & (rd.clean["Compound"] != "UNKNOWN")]
    for comp, g in df.groupby("Compound"):
        if len(g) < 25:
            continue
        g = g.assign(bucket=(g["TyreLife"] // 3) * 3 + 1)
        m = g.groupby("bucket")["rel_delta"].agg(["mean", "count"])
        m = m[m["count"] >= 6]
        if len(m) >= 3:
            deg[comp] = [{"age": int(a), "delta_s": _r(v, 3)} for a, v in m["mean"].items()]

    teams = []
    for team in dict.fromkeys(x.team for x in rd.cars):
        members = [x for x in rd.cars if x.team == team]
        codes = [x.driver_code for x in members]
        tdelta = rd.clean[rd.clean["Team"] == team]["field_delta"]
        cons = [c.consistency[d] for d in codes if d in c.consistency.index and pd.notna(c.consistency[d]) and d in c.eligible]
        best = c.timed[c.timed["Driver"].isin(codes)]["LapTime_s"]
        teams.append({
            "team": team, "drivers": codes,
            "best_position": min(x.position for x in members),
            "dnfs": sum(1 for x in members if x.retired),
            "stops": sum(len(c.pit_laps.get(d, [])) for d in codes),
            "median_delta_s": _r(tdelta.median()) if len(tdelta) >= 20 else None,
            "consistency_s": _r(np.mean(cons)) if cons else None,
            "best_lap": _fmt_lap(float(best.min())) if len(best) else None,
        })
    teams.sort(key=lambda t: (t["median_delta_s"] is None, t["median_delta_s"] if t["median_delta_s"] is not None else 0))

    return {"strategy": strategy, "pace_ranking": pace_ranking, "field_pace": field_pace,
            "lead_timeline": lead_timeline, "deg_curves": deg, "teams": teams,
            "neutral_laps": [int(l) for l in rd.neutral_laps], "total_laps": int(rd.total_laps)}


# ── build + disk cache ────────────────────────────────────────────────────────

def _cache_path(race_id: str) -> Path:
    return Path(settings.cache_dir) / "processed" / "insights" / f"{race_id}_v{INSIGHTS_VERSION}.json"


def race_insights(race_id: str) -> dict:
    """{race_id, event_name, year, circuit, round, insights: [...], facts: {...}} (disk-cached)."""
    from app.engine import storage
    path = _cache_path(race_id)
    source = storage._path(race_id)
    if path.exists() and (not source.exists() or path.stat().st_mtime >= source.stat().st_mtime):
        return json.loads(path.read_text(encoding="utf-8"))

    rd = race_data(race_id)
    if not rd.laps["LapTime_s"].notna().any():
        # e.g. a race stopped on the opening lap — nothing to analyse.
        result = {"race_id": race_id, "event_name": rd.meta.get("event_name"), "year": rd.meta.get("year"),
                  "circuit": rd.meta.get("circuit"), "round": rd.meta.get("round_number"),
                  "insights": [], "facts": None, "extras": None}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result), encoding="utf-8")
        return result
    ctx = _Ctx(rd)
    out = []
    for fn in INSIGHTS:
        try:
            item = fn(ctx)
        except Exception as exc:                # one bad statistic must not sink the rest
            log.warning("insight %s failed for %s: %s", fn.__name__, race_id, exc)
            item = None
        if item:
            out.append(item)
    result = {
        "race_id": race_id,
        "event_name": rd.meta.get("event_name"), "year": rd.meta.get("year"),
        "circuit": rd.meta.get("circuit"), "round": rd.meta.get("round_number"),
        "insights": out, "facts": _facts(ctx), "extras": _extras(ctx),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


def cached_race_ids(year: Optional[int] = None) -> list[str]:
    """Races whose processed lap data is on disk (the only ones we can analyse offline)."""
    from app.engine import storage
    d = Path(settings.cache_dir) / "processed"
    ids = sorted(p.stem for p in d.glob("*.pkl")) if d.exists() else []
    return [i for i in ids if year is None or i.startswith(f"{year}-")]


# ── season roll-ups ───────────────────────────────────────────────────────────

def season_insights(year: int) -> dict:
    """Roll-ups across every cached race of one season."""
    races = []
    for rid in cached_race_ids(year):
        try:
            r = race_insights(rid)
            if r["facts"]:
                races.append(r)
        except Exception as exc:
            log.warning("skipping %s in season roll-up: %s", rid, exc)
    if not races:
        return {"year": year, "races_analysed": 0, "insights": []}

    def tag(r):
        return f"{r['event_name']}"

    F = lambda r: r["facts"]
    out: list[dict] = []
    n = len(races)

    wins = Counter(F(r)["winner"] for r in races)
    d, k = wins.most_common(1)[0]
    out.append(_ins("s_top_winner", "Season", "Most wins", f"{d} ({k})",
                    f"Across {n} analysed races: " + ", ".join(f"{a} {b}" for a, b in wins.most_common(5)) + "."))
    tw = Counter(F(r)["winner_team"] for r in races)
    t, k = tw.most_common(1)[0]
    out.append(_ins("s_top_team", "Season", "Most wins by a team", f"{t} ({k})",
                    ", ".join(f"{a} {b}" for a, b in tw.most_common(4)) + "."))
    pod = Counter(x for r in races for x in F(r)["podium"])
    d, k = pod.most_common(1)[0]
    out.append(_ins("s_podiums", "Season", "Most podiums", f"{d} ({k})", ", ".join(f"{a} {b}" for a, b in pod.most_common(5)) + "."))
    best = min(races, key=lambda r: F(r)["fastest_lap_s"])
    out.append(_ins("s_fastest_lap", "Season", "Fastest lap of the season", f"{F(best)['fastest_lap_driver']} {_fmt_lap(F(best)['fastest_lap_s'])}",
                    f"Set at the {tag(best)}."))
    fl = Counter(F(r)["fastest_lap_driver"] for r in races)
    d, k = fl.most_common(1)[0]
    out.append(_ins("s_fl_count", "Season", "Most fastest laps", f"{d} ({k})"))
    top = max(races, key=lambda r: F(r)["swaps"])
    out.append(_ins("s_most_swaps", "Season", "Most on-track action", tag(top), f"~{F(top)['swaps']} estimated position swaps."))
    top = min(races, key=lambda r: F(r)["swaps"])
    out.append(_ins("s_least_swaps", "Season", "Processional race", tag(top), f"Only ~{F(top)['swaps']} estimated position swaps."))
    top = max(races, key=lambda r: F(r)["neutral_laps"])
    out.append(_ins("s_most_neutral", "Season", "Most neutralised laps", tag(top), f"{F(top)['neutral_laps']} laps under safety car / VSC / red flag."))
    top = max(races, key=lambda r: F(r)["lead_changes"])
    out.append(_ins("s_most_lead_changes", "Season", "Most lead changes", tag(top), f"{F(top)['lead_changes']} changes of the lead."))
    top = max(races, key=lambda r: F(r)["dnfs"])
    out.append(_ins("s_most_dnfs", "Season", "Most retirements", tag(top), f"{F(top)['dnfs']} cars retired."))
    tot_start = sum(F(r)["starters"] for r in races)
    out.append(_ins("s_dnf_rate", "Season", "Retirement rate", f"{100 * sum(F(r)['dnfs'] for r in races) / max(tot_start, 1):.1f}%",
                    "Share of starters that did not finish."))
    out.append(_ins("s_avg_stops", "Season", "Average pit stops per race (all cars)", f"{np.mean([F(r)['stops'] for r in races]):.1f}"))
    top = max(races, key=lambda r: F(r)["stops"])
    out.append(_ins("s_most_stops", "Season", "Most pit stops in a race", tag(top), f"{F(top)['stops']} stops."))
    losses = [F(r)["median_pit_loss"] for r in races if F(r)["median_pit_loss"]]
    if losses:
        out.append(_ins("s_pit_loss", "Season", "Typical pit-stop time loss", f"{np.median(losses):.1f}s", "Median of per-race estimates."))
    comp = Counter()
    for r in races:
        for k2, v in F(r)["compound_laps"].items():
            if k2 != "UNKNOWN":
                comp[k2] += v
    if comp:
        tot = sum(comp.values())
        out.append(_ins("s_compounds", "Season", "Tyre usage across the season", comp.most_common(1)[0][0].title(),
                        " / ".join(f"{k2.title()} {100 * v / tot:.0f}%" for k2, v in comp.most_common()) + " of laps."))
    strat = Counter(F(r)["top_strategy"] for r in races if F(r)["top_strategy"])
    if strat:
        s, k = strat.most_common(1)[0]
        out.append(_ins("s_strategy", "Season", "Most common race strategy", s, f"The top strategy in {k} of {n} races."))
    return {"year": year, "races_analysed": n, "insights": out}
