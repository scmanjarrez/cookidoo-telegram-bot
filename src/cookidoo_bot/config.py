"""Application configuration loaded from config.toml."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CookidooConfig:
    """Cookidoo account and site configuration."""

    username: str
    password: str
    site: str


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bot configuration."""

    token: str
    allowed_ids: list[int]


@dataclass(frozen=True)
class GoogleConfig:
    """Google Gemini API configuration."""

    token: str
    model: str
    thinking_level: str


@dataclass(frozen=True)
class AppConfig:
    """Complete application configuration."""

    cookidoo: CookidooConfig
    telegram: TelegramConfig
    google: GoogleConfig


def load_config(path: Path) -> AppConfig:
    """Load and parse application config from a TOML file."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return AppConfig(
        cookidoo=CookidooConfig(
            username=raw["cookidoo"]["username"],
            password=raw["cookidoo"]["password"],
            site=raw["cookidoo"]["cookidoo-site"],
        ),
        telegram=TelegramConfig(
            token=raw["telegram"]["token"],
            allowed_ids=list(raw["telegram"]["allowed-ids"]),
        ),
        google=GoogleConfig(
            token=raw["google"]["token"],
            model=raw["google"]["model"],
            thinking_level=raw["google"].get("thinking-level", "LOW").upper(),
        ),
    )
