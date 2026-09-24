"""
Vectorised NumPy Monte Carlo race simulator.

simulate_race(current_lap, total_laps, grid_state, n_simulations=1000)
  → list[WinProbability]

Each simulation rolls forward every remaining lap for every car using:
  • Compound degradation curves
  • Gaussian lap-time noise (driver consistency + traffic)
  • Pit-stop time loss
  • Undercut advantage on fresh tyres
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.schemas.race import CarState, TireCompound, WinProbability

log = logging.getLogger(__name__)

# ── Compound degradation (seconds per lap of extra time added) ──────────────
DEGRADATION: dict[str, float] = {
    "SOFT":         0.12,
    "MEDIUM":       0.08,
    "HARD":         0.05,
    "INTERMEDIATE": 0.07,
    "WET":          0.06,
    "UNKNOWN":      0.08,
}

# Base pace delta of each compound vs a theoretical neutral reference (seconds)
# Negative = faster.
BASE_PACE: dict[str, float] = {
    "SOFT":         -0.5,
    "MEDIUM":        0.0,
    "HARD":          0.4,
    "INTERMEDIATE":  1.5,
    "WET":           3.0,
    "UNKNOWN":       0.0,
}

# Gaussian noise std-dev per lap (models driver inconsistency + traffic)
LAP_NOISE_STD: float = 0.25   # seconds

# Roughly how long a compound's tyre life lasts before a stop becomes
# necessary (laps), used only to schedule *future* pit stops inside the
# simulation — real target stint lengths vary by circuit/strategy, so each
# simulated car draws its own target with jitter (see STINT_LENGTH_JITTER_STD)
# rather than every car pitting on exactly the same lap.
STINT_LENGTH_LAPS: dict[str, float] = {
    "SOFT":         20.0,
    "MEDIUM":       30.0,
    "HARD":         40.0,
    "INTERMEDIATE": 25.0,
    "WET":          30.0,
    "UNKNOWN":      30.0,
}
STINT_LENGTH_JITTER_STD: float = 4.0   # laps
MIN_STINT_LENGTH_LAPS: float = 8.0

# Per-race cache of stint-length targets actually observed in this race (see
# _stint_targets_for_race). Tried calibrating DEGRADATION/BASE_PACE from
# historical laps across cached races first — the regression came back with
# *negative* degradation for SOFT and HARD even after removing the race-wide
# fuel-burn/track-evolution trend, i.e. physically backwards, because 5
# cached races isn't enough stint data to separate real degradation from
# noise, traffic and per-circuit differences. Shipping that would have made
# the model worse, not better, so those constants stay hand-picked. Stint
# *length*, though, we don't need to infer statistically — every replayed
# race already tells us, as ground truth, how long the field actually ran
# each compound before pitting, so we use that directly instead of a
# generic textbook assumption.
_stint_target_cache: dict[str, dict[str, float]] = {}


def _stint_targets_for_race(race_id: str) -> dict[str, float]:
    """
    Median completed-stint length per compound, observed in this specific
    race. A driver's last stint in the data is excluded (it hasn't ended in
    a pit stop — it's just wherever the replay currently is — so its length
    isn't evidence of a "typical" stint, only "at least this long").
    Compounds with fewer than 3 completed-stint observations in this race
    fall back to STINT_LENGTH_LAPS.
    """
    if race_id in _stint_target_cache:
        return _stint_target_cache[race_id]

    targets = dict(STINT_LENGTH_LAPS)
    try:
        from app.engine.data_loader import load_stint_data
        lengths_by_compound: dict[str, list[float]] = {}
        for driver in load_stint_data(race_id):
            completed = driver["stints"][:-1]   # drop the still-running final stint
            for stint in completed:
                lengths_by_compound.setdefault(stint["compound"], []).append(stint["laps"])
        for compound, lengths in lengths_by_compound.items():
            if len(lengths) >= 3 and compound in targets:
                targets[compound] = float(np.median(lengths))
    except Exception:
        log.debug("Could not derive stint targets for %s — using defaults", race_id, exc_info=True)

    _stint_target_cache[race_id] = targets
    return targets

# Compound a simulated car switches onto for every pit stop *within* the
# rollout (its first stint keeps whatever compound it's actually on). This
# is a simplification — real strategy varies — but a fixed, durable target
# compound is what stops the simulation from ever needing to guess a whole
# multi-compound strategy tree while still forcing stops to happen at all.
_ROLLOUT_PIT_COMPOUND = "HARD"

# Pit stop time loss (seconds) keyed by circuit substring
PIT_LOSS_BY_CIRCUIT: dict[str, float] = {
    "monza":      22.0,
    "zandvoort":  24.0,
    "monaco":     28.0,
}
DEFAULT_PIT_LOSS: float = 23.0


def _pit_loss(race_id: str) -> float:
    for key, val in PIT_LOSS_BY_CIRCUIT.items():
        if key in race_id.lower():
            return val
    return DEFAULT_PIT_LOSS


def simulate_race(
    current_lap: int,
    total_laps: int,
    grid_state: list[CarState],
    race_id: str = "",
    n_simulations: int = 1000,
) -> list[WinProbability]:
    """
    Run vectorised Monte Carlo simulation for remaining laps.

    Parameters
    ----------
    current_lap   : lap just completed
    total_laps    : race distance
    grid_state    : list of CarState for all active cars
    race_id       : used to look up pit-loss value
    n_simulations : number of MC paths

    Returns
    -------
    list[WinProbability] sorted by win_pct descending, top-10
    """
    if not grid_state:
        return []

    # Retired cars can't win or affect anyone else's finishing order — project
    # win/podium chances only for cars still actually racing, and give
    # retirees a flat 0%/0% at their already-classified (bottom-of-field)
    # position instead of letting them roll forward through the rest of the
    # race as if they were still on track.
    active_state  = [c for c in grid_state if not c.retired]
    retired_state = [c for c in grid_state if c.retired]

    remaining_laps = max(total_laps - current_lap, 0)
    if remaining_laps == 0 or not active_state:
        # Race finished (or nobody left running) – winner is P1 among the
        # still-classified/active field.
        ordering = sorted(grid_state, key=lambda c: c.position)
        p1 = next((c for c in ordering if not c.retired), None)
        return [
            WinProbability(
                car_id=c.car_id,
                driver_code=c.driver_code,
                win_pct=100.0 if (p1 is not None and c.car_id == p1.car_id) else 0.0,
                podium_pct=100.0 if (not c.retired and c.position <= 3) else 0.0,
                expected_position=float(c.position),
            )
            for c in ordering
        ]

    pit_loss = _pit_loss(race_id)
    n_cars = len(active_state)
    rng = np.random.default_rng()

    # ── Build per-car base state arrays ─────────────────────────────────────
    # Shape: (n_cars,)
    cum_times   = np.array([c.cumulative_time_s for c in active_state], dtype=np.float64)
    tire_ages   = np.array([c.tire_age_laps      for c in active_state], dtype=np.float64)
    compounds   = [c.tire_compound for c in active_state]
    deg_rates   = np.array([DEGRADATION.get(cp, 0.08) for cp in compounds])
    base_paces  = np.array([BASE_PACE.get(cp, 0.0)    for cp in compounds])

    # ── Broadcast to (n_simulations, n_cars) ────────────────────────────────
    cum_matrix  = np.tile(cum_times,  (n_simulations, 1))   # (S, C)
    deg_matrix  = np.tile(deg_rates,  (n_simulations, 1))   # current compound's degradation rate — changes on a pit
    pace_matrix = np.tile(base_paces, (n_simulations, 1))   # current compound's base pace — changes on a pit
    age_matrix  = np.tile(tire_ages,  (n_simulations, 1))   # current tyre age — increments each lap, resets on a pit

    # Ground the assumed stint length in what the field actually did in this
    # race so far, rather than a generic textbook figure — see
    # _stint_targets_for_race for why we use real per-race ground truth here
    # instead of trying to statistically infer it across races.
    stint_lengths = _stint_targets_for_race(race_id)

    pit_deg  = DEGRADATION[_ROLLOUT_PIT_COMPOUND]
    pit_pace = BASE_PACE[_ROLLOUT_PIT_COMPOUND]
    pit_stint_len = stint_lengths[_ROLLOUT_PIT_COMPOUND]

    # Each car's current stint has its own target length (with jitter) at
    # which it pits again during the rollout — otherwise every simulated car
    # on a given compound would pit on exactly the same lap.
    base_stint_len = np.array([stint_lengths.get(cp, 30.0) for cp in compounds])
    stint_target = np.tile(base_stint_len, (n_simulations, 1)) + rng.normal(
        0.0, STINT_LENGTH_JITTER_STD, (n_simulations, n_cars)
    )
    stint_target = np.maximum(stint_target, MIN_STINT_LENGTH_LAPS)

    # Roll forward each lap. Tyre age is tracked as real per-lap state (not
    # `starting_age + lap_offset`, which would mean the car NEVER pits again
    # for the rest of the race) so a stop actually happens once a car's
    # current stint passes its target length — without this, a compound
    # with a flatter degradation curve just keeps "winning" the fantasy of
    # an ever-lengthening single stint, however far behind it really is.
    for _ in range(remaining_laps):
        age_matrix += 1.0
        deg_penalty = deg_matrix * age_matrix

        # Gaussian noise
        noise = rng.normal(0.0, LAP_NOISE_STD, (n_simulations, n_cars))

        # Stochastic safety car / VSC event: ~8 % chance per lap adds 15-30 s to all
        sc_event = rng.random(n_simulations) < 0.08
        sc_loss  = rng.uniform(15, 30, n_simulations) * sc_event
        sc_loss  = sc_loss[:, np.newaxis]  # broadcast over cars

        # A car pits this lap if its current stint has run past its target.
        pit_mask = age_matrix >= stint_target

        # Lap time = base_pace + degradation + noise (+ pit-lane loss if pitting)
        lap_time = 90.0 + pace_matrix + deg_penalty + noise + sc_loss
        lap_time = np.where(pit_mask, lap_time + pit_loss, lap_time)
        lap_time = np.maximum(lap_time, 60.0)   # floor (safety car stints)

        cum_matrix += lap_time

        # Reset state for cars that pitted: fresh tyre, new compound, and a
        # freshly-jittered target for their next stint.
        age_matrix  = np.where(pit_mask, 0.0, age_matrix)
        deg_matrix  = np.where(pit_mask, pit_deg, deg_matrix)
        pace_matrix = np.where(pit_mask, pit_pace, pace_matrix)
        new_target = pit_stint_len + rng.normal(0.0, STINT_LENGTH_JITTER_STD, (n_simulations, n_cars))
        stint_target = np.where(pit_mask, np.maximum(new_target, MIN_STINT_LENGTH_LAPS), stint_target)

    # ── Resolve finishing positions ──────────────────────────────────────────
    # argsort each row: lower cumulative time → better position
    positions = np.argsort(np.argsort(cum_matrix, axis=1), axis=1) + 1   # (S, C)

    win_counts    = (positions == 1).sum(axis=0)           # (C,)
    podium_counts = (positions <= 3).sum(axis=0)
    avg_pos       = positions.mean(axis=0)

    results: list[WinProbability] = []
    for i, car in enumerate(active_state):
        results.append(
            WinProbability(
                car_id=car.car_id,
                driver_code=car.driver_code,
                win_pct=round(float(win_counts[i]) / n_simulations * 100, 2),
                podium_pct=round(float(podium_counts[i]) / n_simulations * 100, 2),
                expected_position=round(float(avg_pos[i]), 2),
            )
        )
    for car in retired_state:
        results.append(
            WinProbability(
                car_id=car.car_id,
                driver_code=car.driver_code,
                win_pct=0.0,
                podium_pct=0.0,
                expected_position=float(car.position),
            )
        )

    return sorted(results, key=lambda r: r.win_pct, reverse=True)


def simulate_counterfactual(
    current_lap: int,
    total_laps: int,
    grid_state: list[CarState],
    car_id: int,
    pit_lap: int,
    target_compound: str,
    race_id: str = "",
    n_simulations: int = 1000,
) -> tuple[WinProbability, WinProbability]:
    """
    Run baseline simulation vs. counterfactual (car_id pits on pit_lap
    for target_compound).

    Returns (original_wp, counterfactual_wp) for car_id.
    """
    # Baseline
    baseline_probs = simulate_race(current_lap, total_laps, grid_state, race_id, n_simulations)
    orig = next((p for p in baseline_probs if p.car_id == car_id), None)

    # Build counterfactual grid: modify the target car's tyres
    cf_grid: list[CarState] = []
    for car in grid_state:
        if car.car_id == car_id:
            # Pit on pit_lap: subtract pit_loss from gap, reset tyre age, new compound
            pit_loss = _pit_loss(race_id)
            laps_until_pit = max(pit_lap - current_lap, 0)
            # Penalise cumulative time by pit-loss minus any future pace gain
            pace_gain_per_lap = (
                BASE_PACE.get(car.tire_compound, 0.0)
                - BASE_PACE.get(target_compound, 0.0)
            )
            net_gain = pace_gain_per_lap * (total_laps - pit_lap) - pit_loss
            cf_car = car.model_copy(update={
                "tire_compound": target_compound,
                "tire_age_laps": 0,
                "cumulative_time_s": car.cumulative_time_s + pit_loss - max(net_gain, 0),
            })
            cf_grid.append(cf_car)
        else:
            cf_grid.append(car)

    cf_probs = simulate_race(current_lap, total_laps, cf_grid, race_id, n_simulations)
    cf = next((p for p in cf_probs if p.car_id == car_id), None)

    if orig is None or cf is None:
        raise ValueError(f"car_id {car_id} not found in grid_state")

    return orig, cf


def calculate_undercut(
    current_lap: int,
    total_laps: int,
    grid_state: list[CarState],
    car_id: int,
    target_car_id: int,
    pit_lap: int,
    target_compound: str,
    race_id: str = "",
) -> dict:
    """
    Calculate whether pitting car_id on pit_lap will undercut target_car_id.
    Returns will_undercut, gap projections, and breakeven lap.
    """
    pit_loss = _pit_loss(race_id)

    car = next((c for c in grid_state if c.car_id == car_id), None)
    target = next((c for c in grid_state if c.car_id == target_car_id), None)

    if car is None or target is None:
        return {
            "will_undercut": False,
            "gap_before_s": 0.0,
            "projected_gap_after_s": 0.0,
            "breakeven_lap": None,
            "recommendation": "Driver not found in grid.",
        }

    gap_before = car.cumulative_time_s - target.cumulative_time_s
    remaining_after_pit = total_laps - pit_lap

    new_pace = BASE_PACE.get(target_compound, 0.0)
    current_pace = BASE_PACE.get(car.tire_compound, 0.0)
    pace_gain_per_lap = current_pace - new_pace

    current_deg = DEGRADATION.get(car.tire_compound, 0.08) * car.tire_age_laps
    gap_after_pit = gap_before + pit_loss - (pace_gain_per_lap + current_deg) * remaining_after_pit

    will_undercut = gap_after_pit < 0

    breakeven: int | None = None
    if pace_gain_per_lap > 0:
        n_laps = int(pit_loss / pace_gain_per_lap) + 1
        candidate = pit_lap + n_laps
        if candidate <= total_laps:
            breakeven = candidate

    if will_undercut:
        rec = (
            f"Undercut works. {car.driver_code} projects {abs(gap_after_pit):.1f}s "
            f"ahead of {target.driver_code} by race end."
        )
    elif breakeven is not None:
        rec = (
            f"Undercut marginal. {car.driver_code} overtakes {target.driver_code} "
            f"around lap {breakeven}."
        )
    else:
        rec = (
            f"Overcut recommended. Gap projected at +{gap_after_pit:.1f}s — "
            f"insufficient pace gain from {target_compound}."
        )

    return {
        "will_undercut": will_undercut,
        "gap_before_s": round(gap_before, 3),
        "projected_gap_after_s": round(gap_after_pit, 3),
        "breakeven_lap": breakeven,
        "recommendation": rec,
    }


def calculate_optimal_stop(
    current_lap: int,
    total_laps: int,
    car_state: CarState,
    race_id: str = "",
    compounds_available: list[str] | None = None,
) -> list[dict]:
    """
    For each available compound, find the optimal pit window.
    Returns list of {compound, earliest_lap, latest_lap, optimal_lap, net_time_gain_s}.
    """
    if compounds_available is None:
        compounds_available = ["MEDIUM", "HARD"]

    pit_loss = _pit_loss(race_id)
    results = []

    for compound in compounds_available:
        if compound == car_state.tire_compound:
            continue

        new_pace = BASE_PACE.get(compound, 0.0)
        current_pace_val = BASE_PACE.get(car_state.tire_compound, 0.0)
        new_deg = DEGRADATION.get(compound, 0.08)
        current_deg = DEGRADATION.get(car_state.tire_compound, 0.08)

        best_net_gain = float("-inf")
        best_lap = current_lap + 1

        for pit_lap in range(current_lap + 1, total_laps - 4):
            remaining = total_laps - pit_lap
            age_at_pit = car_state.tire_age_laps + (pit_lap - current_lap)

            pace_delta = current_pace_val - new_pace
            pace_gain = pace_delta * remaining

            deg_saving = sum(
                current_deg * (age_at_pit + i) - new_deg * i
                for i in range(remaining)
            )

            net_gain = pace_gain + deg_saving - pit_loss
            if net_gain > best_net_gain:
                best_net_gain = net_gain
                best_lap = pit_lap

        earliest = best_lap
        latest = best_lap

        for dl in range(1, 8):
            lap_candidate = best_lap - dl
            if lap_candidate > current_lap:
                remaining = total_laps - lap_candidate
                net = (current_pace_val - new_pace) * remaining - pit_loss
                if net > 0:
                    earliest = lap_candidate

        for dl in range(1, 8):
            lap_candidate = best_lap + dl
            if lap_candidate < total_laps - 5:
                remaining = total_laps - lap_candidate
                net = (current_pace_val - new_pace) * remaining - pit_loss
                if net > 0:
                    latest = lap_candidate

        results.append({
            "compound": compound,
            "earliest_lap": earliest,
            "latest_lap": latest,
            "optimal_lap": best_lap,
            "net_time_gain_s": round(best_net_gain, 2),
        })

    return sorted(results, key=lambda r: -r["net_time_gain_s"])
