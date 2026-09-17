from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "SAK RACING SIM"
    debug: bool = True
    cache_dir: str = str(Path(__file__).resolve().parents[3] / "cache")
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    pit_loss_monza: float = 22.0
    pit_loss_zandvoort: float = 24.0

    class Config:
        env_file = ".env"


settings = Settings()
