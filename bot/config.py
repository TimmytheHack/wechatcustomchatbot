from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError
from zoneinfo import ZoneInfo


class QuietHoursBlock(BaseModel):
    start: str
    end: str


class ProactiveConfig(BaseModel):
    enabled: bool = False
    max_per_day: int = 1
    cooldown_hours: int = 6
    min_confidence: float = 0.6
    max_pending_per_chat: int = 2


class GroupConfig(BaseModel):
    allow_proactive: bool = False
    reply_only_when_mentioned: bool = True


class SecurityConfig(BaseModel):
    shared_secret: str


class RuntimeConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    scheduler_interval_seconds: int = 20
    db_path: str = "data/bot.db"
    connector: str = "bot.connector_stub:StubConnector"


class MemoryConfig(BaseModel):
    recent_messages: int = 30
    summary_max_chars: int = 1200


class Settings(BaseModel):
    timezone: str
    tone: str
    gif_rate: Literal["off", "low", "medium", "high"] = "medium"
    gif_folder: str = "assets/gifs"
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    quiet_hours: list[QuietHoursBlock] = Field(default_factory=list)
    groups: GroupConfig = Field(default_factory=GroupConfig)
    security: SecurityConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)


class EnvConfig(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None


class SettingsError(RuntimeError):
    pass


def load_settings(path: str) -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        raise SettingsError(f"Config file not found: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(f"Invalid config: {exc}") from exc
    try:
        ZoneInfo(settings.timezone)
    except Exception as exc:  # pragma: no cover - config validation
        raise SettingsError(f"Invalid timezone: {settings.timezone}") from exc
    return settings


def load_env() -> EnvConfig:
    # Env vars are optional; keep minimal to allow dummy mode.
    from dotenv import load_dotenv

    load_dotenv()
    import os

    return EnvConfig(
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL"),
    )
