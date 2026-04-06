"""Bot setup and entry point."""

import logging
from pathlib import Path

from google import genai
from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder, CommandHandler

from .ai_service import RecipeAIService
from .config import AppConfig, load_config
from .handlers import build_conv_handler, set_language
from .i18n import Localizer
from .recipe_service import RecipeService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

_BASE = Path(__file__).parent.parent.parent
_CONFIG_PATH = _BASE / "config.toml"
_LANGUAGES_PATH = _BASE / "languages"
_LANG_FILE = _BASE / ".lang"

_COMMANDS = [
    BotCommand("create", "Adapt and/or translate a Cookidoo recipe"),
    BotCommand("language", "Change the bot UI language (e.g. /language es)"),
    BotCommand("cancel", "Cancel the current operation"),
]


async def _post_init(application: Application) -> None:
    cfg: AppConfig = application.bot_data["config"]

    # Persisted language preference
    application.bot_data["lang_path"] = _LANG_FILE
    default_lang = "en"
    if _LANG_FILE.exists():
        stored = _LANG_FILE.read_text().strip()
        if stored:
            default_lang = stored
    application.bot_data["default_lang"] = default_lang

    gemini_client = genai.Client(api_key=cfg.google.token)
    ai_service = RecipeAIService(gemini_client, cfg.google)
    application.bot_data["recipe_service"] = RecipeService(
        cfg.cookidoo, ai_service
    )
    application.bot_data["localizer"] = Localizer(_LANGUAGES_PATH)

    await application.bot.set_my_commands(_COMMANDS)


async def _post_stop(application: Application) -> None:
    await application.bot.delete_my_commands()


def main() -> None:
    """Configure and start the Telegram bot."""
    cfg = load_config(_CONFIG_PATH)

    app: Application = (
        ApplicationBuilder()
        .token(cfg.telegram.token)
        .post_init(_post_init)
        .post_stop(_post_stop)
        .build()
    )
    app.bot_data["config"] = cfg

    app.add_handler(CommandHandler("language", set_language))
    app.add_handler(build_conv_handler())
    app.run_polling()
