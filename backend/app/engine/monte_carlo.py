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

    remaining_laps = max(total_laps - current_lap, 0)
    if remaining_laps == 0:
        # Race finished – winner is P1
        p1 = min(grid_state, key=lambda c: c.position)
        return [
            WinProbability(
                car_id=c.car_id,
                driver_code=c.driver_code,
                win_pct=100.0 if c.car_id == p1.car_id else 0.0,
                podium_pct=100.0 if c.position <= 3 else 0.0,
                expected_position=float(c.position),
            )
            for c in sorted(grid_state, key=lambda x: x.position)
        ]

    pit_loss = _pit_loss(race_id)
    n_cars = len(grid_state)
    rng = np.random.default_rng()

    # ── Build per-car base state arrays ─────────────────────────────────────
    # Shape: (n_cars,)
    cum_times   = np.array([c.cumulative_time_s for c in grid_state], dtype=np.float64)
    tire_ages   = np.array([c.tire_age_laps      for c in grid_state], dtype=np.float64)
    compounds   = [c.tire_compound for c in grid_state]
    deg_rates   = np.array([DEGRADATION.get(cp, 0.08) for cp in compounds])
    base_paces  = np.array([BASE_PACE.get(cp, 0.0)    for cp in compounds])

    # ── Broadcast to (n_simulations, n_cars) ────────────────────────────────
    cum_matrix  = np.tile(cum_times,  (n_simulations, 1))   # (S, C)
    age_matrix  = np.tile(tire_ages,  (n_simulations, 1))
    deg_matrix  = np.tile(deg_rates,  (n_simulations, 1))
    pace_matrix = np.tile(base_paces, (n_simulations, 1))

    # Roll forward each lap
    for lap_offset in range(remaining_laps):
        # Degradation penalty grows with tyre age
        deg_penalty = deg_matrix * (age_matrix + lap_offset)

        # Gaussian noise
        noise = rng.normal(0.0, LAP_NOISE_STD, (n_simulations, n_cars))

        # Stochastic safety car / VSC event: ~8 % chance per lap adds 15-30 s to all
        sc_event = rng.random(n_simulations) < 0.08
        sc_loss  = rng.uniform(15, 30, n_simulations) * sc_event
        sc_loss  = sc_loss[:, np.newaxis]  # broadcast over cars

        # Lap time = base_pace + degradation + noise
        lap_time = 90.0 + pace_matrix + deg_penalty + noise + sc_loss
        lap_time = np.maximum(lap_time, 60.0)   # floor (safety car stints)

        cum_matrix += lap_time

    # ── Resolve finishing positions ──────────────────────────────────────────
    # argsort each row: lower cumulative time → better position
    positions = np.argsort(np.argsort(cum_matrix, axis=1), axis=1) + 1   # (S, C)

    win_counts    = (positions == 1).sum(axis=0)           # (C,)
    podium_counts = (positions <= 3).sum(axis=0)
    avg_pos       = positions.mean(axis=0)

    results: list[WinProbability] = []
    for i, car in enumerate(grid_state):
        results.append(
            WinProbability(
                car_id=car.car_id,
                driver_code=car.driver_code,
                win_pct=round(float(win_counts[i]) / n_simulations * 100, 2),
                podium_pct=round(float(podium_counts[i]) / n_simulations * 100, 2),
                expected_position=round(float(avg_pos[i]), 2),
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
