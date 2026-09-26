"""Trajectory smoothing + excursion detection, on synthetic tracks with known answers."""
import numpy as np
import pytest

from app.engine import trajectory as tr


def _circle(radius=200.0, n=400):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([radius * np.cos(a), radius * np.sin(a)])   # anticlockwise → turning left


def test_catmull_rom_passes_through_samples():
    rng = np.random.default_rng(0)
    pts = np.cumsum(rng.normal(size=(12, 2)) * 10, axis=0)
    knots = tr._centripetal_knots(pts)
    out = tr._catmull_rom(pts, knots, knots)
    assert np.allclose(out, pts, atol=1e-9)


def test_smooth_path_is_60hz_and_follows_speed():
    # straight line sampled unevenly, constant 50 m/s: output spacing must be uniform
    t = np.array([0.0, 0.1, 0.35, 0.4, 0.8, 1.0, 1.5, 2.0])
    xy = np.column_stack([50 * t, np.zeros_like(t)])
    p = tr.smooth_path(t, xy, t, np.full_like(t, 50.0))
    assert len(p["t"]) >= 2.0 * tr.SAMPLE_HZ
    step = np.diff(p["x"])
    assert np.allclose(step[:-1], 50 / tr.SAMPLE_HZ, atol=1e-6)
    assert np.allclose(p["heading"], 0.0, atol=1e-9)


def test_heading_turns_smoothly_around_a_corner():
    a = np.linspace(0, np.pi / 2, 9)
    xy = np.column_stack([30 * np.cos(a), 30 * np.sin(a)])
    t = np.linspace(0, 2, 9)
    p = tr.smooth_path(t, xy, t, np.full_like(t, 30 * (np.pi / 2) / 2))
    dh = np.diff(p["heading"])
    assert np.all(dh > -1e-6)                               # always turning the same way
    assert np.degrees(np.abs(dh).max()) < 3.0


def test_lateral_offset_sign_and_size():
    ref = tr.reference_line(_circle())
    # 3 m outside the circle = right of travel when going anticlockwise
    a = np.linspace(0.2, 0.6, 20)
    outside = np.column_stack([203 * np.cos(a), 203 * np.sin(a)])
    off, _ = tr.lateral_offsets(outside, ref)
    assert np.allclose(off, -3.0, atol=0.1)


def _run_with_bump(depth, side, t_len=10.0, hz=60.0):
    ref = tr.reference_line(_circle())
    t = np.arange(0, t_len, 1 / hz)
    ang = 0.05 + 0.08 * t                                   # moving anticlockwise
    bump = np.where((t > 4) & (t < 6), np.sin(np.pi * (t - 4) / 2) * (tr.DEFAULT_THRESHOLD_M + depth), 0.0)
    r = 200.0 + (bump if side == "outside" else -bump)
    xy = np.column_stack([r * np.cos(ang), r * np.sin(ang)])
    off, idx = tr.lateral_offsets(xy, ref)
    return tr.find_excursions(t, off, idx, ref, tr.DEFAULT_THRESHOLD_M, [])


def test_detects_excursion_with_duration_and_depth():
    ex = _run_with_bump(depth=2.0, side="outside")
    assert len(ex) == 1
    e = ex[0]
    assert e["max_excursion_m"] == pytest.approx(2.0, abs=0.1)
    # |offset| > 5 of a 7 m half-sine over 4..6 s: asin(5/7)/pi*2 s from each end
    expected = 2 - 2 * 2 * np.arcsin(5 / 7) / np.pi
    assert e["duration_s"] == pytest.approx(expected, abs=0.03)
    assert e["t_exit"] - e["t_entry"] == pytest.approx(e["duration_s"], abs=1e-3)
    assert e["kind"] == "ran wide" and e["side"] == "right"


def test_inside_excursion_is_a_corner_cut():
    ex = _run_with_bump(depth=2.0, side="inside")
    assert len(ex) == 1 and ex[0]["kind"] == "corner cut" and ex[0]["side"] == "left"


def test_small_deviation_is_ignored_as_noise():
    assert _run_with_bump(depth=0.3, side="outside") == []


def test_teleporting_samples_are_dropped():
    ref = tr.reference_line(_circle())
    t = np.arange(10) * 0.25
    a = 0.05 + 0.05 * np.arange(10)                        # ~10 m steps at 40 m/s
    xy = np.column_stack([200 * np.cos(a), 200 * np.sin(a)])
    xy[4] = [900.0, 900.0]                                 # far off the circuit
    xy[7] = xy[7] * 1.35                                   # 70 m sideways in 0.25 s
    ok = tr.drop_glitches(t, xy, np.full(10, 40.0), ref)
    assert ok.tolist() == [True] * 4 + [False] + [True] * 2 + [False] + [True] * 2


def test_placeholder_samples_at_lap_start_do_not_poison_the_rest():
    # lap opens with three samples stuck at one spot 40 m off the track while
    # the car is really moving; the real samples after them must all survive
    ref = tr.reference_line(_circle())
    t = np.arange(12) * 0.25
    a = 0.05 + 0.05 * np.arange(12)
    xy = np.column_stack([200 * np.cos(a), 200 * np.sin(a)])
    xy[:3] = [[160.0, 60.0]] * 3
    ok = tr.drop_glitches(t, xy, np.full(12, 40.0), ref)
    assert ok.tolist() == [False] * 3 + [True] * 9


def test_data_gap_follows_the_track_not_a_chord():
    ref = tr.reference_line(_circle())
    a = np.concatenate([np.linspace(0.0, 0.5, 6), np.linspace(2.5, 3.0, 6)])   # 2 rad of circle missing
    t = np.concatenate([np.linspace(0, 1.25, 6), np.linspace(11.25, 12.5, 6)])
    xy = np.column_stack([200 * np.cos(a), 200 * np.sin(a)])
    ft, fxy, gaps = tr.fill_gaps(t, xy, ref)
    assert gaps == [(1.25, 11.25)]
    assert np.all(np.diff(ft) > 0)
    assert np.abs(np.hypot(*fxy.T) - 200).max() < 1.0          # stays on the circle through the gap


def test_backtracking_samples_are_dropped():
    ref = tr.reference_line(_circle())
    a = np.array([0.10, 0.12, 0.119, 0.14, 0.16])           # third sample steps backwards
    xy = np.column_stack([200 * np.cos(a), 200 * np.sin(a)])
    keep = tr.drop_backtracking(np.arange(5.0), xy, ref)
    assert keep.tolist() == [True, True, False, True, True]
