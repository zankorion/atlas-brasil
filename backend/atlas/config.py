"""Configuração central (variáveis de ambiente com prefixo ATLAS_)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATLAS_", env_file=ROOT / ".env", extra="ignore")

    # PostgreSQL/PostGIS em produção (docker-compose); SQLite como padrão local sem dependências.
    database_url: str = f"sqlite:///{(ROOT / 'data' / 'atlas.db').as_posix()}"
    data_dir: Path = ROOT / "data"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Teto de memória (MB) para os quadros de dados mantidos em cache pela API.
    cache_mb: int = 400
    http_timeout: float = 300.0
    http_retries: int = 4
    user_agent: str = "atlas-brasil/0.1 (plataforma aberta de dados publicos)"
    # Primeiro ano completo após o Plano Real.
    start_year: int = 1995

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def geo_dir(self) -> Path:
        return self.data_dir / "geo"


settings = Settings()
for _d in (settings.data_dir, settings.raw_dir, settings.geo_dir):
    _d.mkdir(parents=True, exist_ok=True)
