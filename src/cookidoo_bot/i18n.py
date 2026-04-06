"""Internationalisation: load per-language TOML files and format strings."""

import tomllib
from pathlib import Path


class Localizer:
    """Loads per-language TOML files and formats translated strings."""

    def __init__(self, languages_path: Path) -> None:
        """Initialize with the path to the TOML language files directory."""
        self._path = languages_path
        self._cache: dict[str, dict[str, str]] = {}

    def _load(self, lang: str) -> dict[str, str]:
        if lang in self._cache:
            return self._cache[lang]
        path = self._path / f"{lang}.toml"
        if not path.exists():
            return self._load("en") if lang != "en" else {}
        with path.open("rb") as f:
            data = tomllib.load(f)
        self._cache[lang] = data
        return data

    def t(self, lang: str, key: str, **kwargs: object) -> str:
        """Return the translated string for *key*, with English fallback."""
        template = self._load(lang).get(key) or self._load("en").get(key, key)
        return template.format(**kwargs) if kwargs else template

    def available(self) -> list[str]:
        """Return sorted list of available language codes."""
        if not self._path.exists():
            return ["en"]
        return sorted(p.stem for p in self._path.glob("*.toml"))


# Map of ISO 639-1 code → English language name used in Gemini prompts
LANG_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
}


def lang_display(code: str) -> str:
    """Return the English name for a language code, e.g. 'es' → 'Spanish'."""
    return LANG_NAMES.get(code, code.upper())
