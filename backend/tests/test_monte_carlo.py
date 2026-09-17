"""Tests for the Monte Carlo simulation engine."""
import pytest
from app.engine.monte_carlo import simulate_race, simulate_counterfactual
from app.schemas.race import CarState


def _make_grid(n: int = 5) -> list[CarState]:
    compounds = ["SOFT", "MEDIUM", "HARD", "MEDIUM", "HARD"]
    drivers   = ["VER", "HAM", "LEC", "SAI", "ALO"]
    return [
        CarState(
            car_id=i + 1,
            driver_code=drivers[i],
            team="Team" + str(i),
            position=i + 1,
            lap_number=10,
            cumulative_time_s=900.0 + i * 20.0,
            gap_to_leader_s=float(i * 20),
            tire_compound=compounds[i],
            tire_age_laps=10,
        )
        for i in range(n)
    ]


def test_simulate_race_returns_probabilities():
    grid = _make_grid(5)
    probs = simulate_race(10, 53, grid, race_id="2023-monza", n_simulations=200)
    assert len(probs) >= 1
    total_win = sum(p.win_pct for p in probs)
    assert abs(total_win - 100.0) < 2.0, f"Win pcts should sum ~100, got {total_win}"


def test_simulate_race_leader_higher_win_pct():
    """
    Build a grid where P1 is significantly ahead on Hard tyres (low degradation)
    so the leader has a clear probabilistic advantage.
    """
    from app.schemas.race import CarState
    grid = [
        CarState(
            car_id=i + 1,
            driver_code=["VER", "HAM", "LEC", "SAI", "ALO"][i],
            team="T",
            position=i + 1,
            lap_number=5,
            cumulative_time_s=450.0 + i * 30.0,  # 30 s gaps — clear leader
            gap_to_leader_s=float(i * 30),
            tire_compound="HARD",     # same compound: pure position advantage
            tire_age_laps=5,
        )
        for i in range(5)
    ]
    probs = simulate_race(5, 53, grid, race_id="2023-monza", n_simulations=500)
    leader_prob = next(p for p in probs if p.car_id == 1)
    others_max  = max(p.win_pct for p in probs if p.car_id != 1)
    assert leader_prob.win_pct > others_max, (
        f"Leader win_pct ({leader_prob.win_pct}) should exceed best rival ({others_max})"
    )


def test_counterfactual_returns_two_probs():
    grid = _make_grid(5)
    orig, cf = simulate_counterfactual(
        current_lap=10,
        total_laps=53,
        grid_state=grid,
        car_id=2,
        pit_lap=15,
        target_compound="HARD",
        race_id="2023-monza",
        n_simulations=200,
    )
    assert orig.car_id == 2
    assert cf.car_id == 2


def test_finished_race_gives_p1_hundred_pct():
    grid = _make_grid(3)
    probs = simulate_race(53, 53, grid, n_simulations=100)
    winner = next(p for p in probs if p.car_id == 1)
    assert winner.win_pct == 100.0
