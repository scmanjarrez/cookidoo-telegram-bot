"""Application configuration loaded from config.toml."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CookidooConfig:
    username: str
    password: str
    site: str


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    admin_id: int


@dataclass(frozen=True)
class GoogleConfig:
    token: str
    model: str
    thinking_level: str


@dataclass(frozen=True)
class AppConfig:
    cookidoo: CookidooConfig
    telegram: TelegramConfig
    google: GoogleConfig


def load_config(path: Path) -> AppConfig:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return AppConfig(
        cookidoo=CookidooConfig(
            username=raw["cookidoo"]["username"],
            password=raw["cookidoo"]["password"],
            site=raw["cookidoo"]["cookidoo-site"],
        ),
        telegram=TelegramConfig(
            token=raw["telegram"]["token"],
            admin_id=raw["telegram"]["admin-id"],
        ),
        google=GoogleConfig(
            token=raw["google"]["token"],
            model=raw["google"]["model"],
            thinking_level=raw["google"].get("thinking-level", "LOW").upper(),
        ),
    )
