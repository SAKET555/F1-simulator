from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal, Optional


TireCompound = Literal["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]


class CarState(BaseModel):
    car_id: int
    driver_code: str
    team: str
    position: int
    lap_number: int
    lap_time_s: Optional[float] = None        # seconds
    cumulative_time_s: float
    gap_to_leader_s: float
    tire_compound: TireCompound = "UNKNOWN"
    tire_age_laps: int = 0
    pit_count: int = 0
    is_in_pit: bool = False
    speed_kmh: Optional[float] = None
    drs: bool = False


class RaceState(BaseModel):
    race_id: str
    lap: int
    total_laps: int
    session_name: str
    cars: list[CarState]
    timestamp_ms: float                        # wall-clock sim time


class WinProbability(BaseModel):
    car_id: int
    driver_code: str
    win_pct: float = Field(ge=0.0, le=100.0)
    podium_pct: float = Field(ge=0.0, le=100.0)
    expected_position: float


class PredictionFrame(BaseModel):
    lap: int
    probabilities: list[WinProbability]
    n_simulations: int


class RaceMeta(BaseModel):
    race_id: str
    year: int
    round_number: int
    event_name: str
    circuit: str
    total_laps: int
    cached: bool


class CounterfactualRequest(BaseModel):
    race_id: str
    car_id: int
    pit_lap: int
    target_compound: TireCompound
    current_lap: Optional[int] = None  # actual replay lap; falls back to last data lap


class CounterfactualResponse(BaseModel):
    car_id: int
    driver_code: str
    original_win_pct: float
    new_win_pct: float
    delta_win_pct: float
    original_podium_pct: float
    new_podium_pct: float
    delta_podium_pct: float
    explanation: str


class WebSocketMessage(BaseModel):
    type: Literal["race_state", "prediction", "race_end", "error", "info"]
    payload: dict


class TelemetryPoint(BaseModel):
    time_s: float
    speed_kmh: float
    throttle: float
    brake: bool
    gear: int
    rpm: int
    drs: int
    x: float
    y: float


class TelemetryResponse(BaseModel):
    driver_code: str
    lap: int
    points: list[TelemetryPoint]


class QualifyingResult(BaseModel):
    position: int
    driver_code: str
    team: str
    q1_s: Optional[float] = None
    q2_s: Optional[float] = None
    q3_s: Optional[float] = None


class GapHistoryResponse(BaseModel):
    race_id: str
    laps: list[int]
    drivers: list[str]
    gaps_matrix: list[list[float]]


class SectorLap(BaseModel):
    lap: int
    s1_s: Optional[float] = None
    s2_s: Optional[float] = None
    s3_s: Optional[float] = None


class SectorResponse(BaseModel):
    driver_code: str
    laps: list[SectorLap]


class ChampionshipEntry(BaseModel):
    position: int
    driver_code: str
    team: str
    points: float
    wins: int
    podiums: int


class ConstructorEntry(BaseModel):
    position: int
    team: str
    points: float
    wins: int


class WeatherFrame(BaseModel):
    lap: int
    air_temp_c: float
    track_temp_c: float
    rainfall: bool
    humidity: float
    wind_speed_ms: float


class WeatherResponse(BaseModel):
    race_id: str
    frames: list[WeatherFrame]


class UndercutRequest(BaseModel):
    race_id: str
    car_id: int
    target_car_id: int
    current_lap: int
    pit_lap: int
    target_compound: TireCompound


class UndercutResponse(BaseModel):
    will_undercut: bool
    gap_before_s: float
    projected_gap_after_s: float
    breakeven_lap: Optional[int] = None
    recommendation: str


class OptimalStopRequest(BaseModel):
    race_id: str
    car_id: int
    current_lap: int
    total_laps: int
    current_compound: TireCompound
    current_tire_age: int
    compounds_available: list[TireCompound]


class OptimalStopWindow(BaseModel):
    compound: str
    earliest_lap: int
    latest_lap: int
    optimal_lap: int
    net_time_gain_s: float


class StintData(BaseModel):
    driver_code: str
    stints: list[dict]
