"""/ language command handler."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from telegram import Update
    from telegram.ext import ContextTypes

    from cookidoo_bot.i18n import Localizer


def _localizer(context: ContextTypes.DEFAULT_TYPE) -> Localizer:
    return context.bot_data["localizer"]


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    user_data = context.user_data or {}
    return user_data.get("lang") or context.bot_data.get("default_lang", "en")


async def set_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the /language command to set the bot's UI language."""
    if update.message is None:
        logger.warning("set_language: missing message")
        return
    localizer = _localizer(context)
    lang = _lang(context)
    available = localizer.available()
    if context.user_data is None:
        await update.message.reply_text(
            localizer.t(
                lang, "error_unexpected", error="session not initialised"
            )
        )
        return

    if not context.args:
        await update.message.reply_text(
            localizer.t(lang, "language_usage", available=", ".join(available))
        )
        return

    code = context.args[0].lower()
    if code not in available:
        await update.message.reply_text(
            localizer.t(
                lang,
                "language_unknown",
                code=code,
                available=", ".join(available),
            )
        )
        return

    # Persist language choice
    lang_path: Path = context.bot_data["lang_path"]
    await asyncio.to_thread(lang_path.write_text, code)
    context.bot_data["default_lang"] = code
    context.user_data["lang"] = code

    await update.message.reply_text(
        localizer.t(code, "language_set", language=code)
    )
