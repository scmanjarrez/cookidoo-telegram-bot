"""/help command handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

    from cookidoo_bot.i18n import Localizer

logger = logging.getLogger(__name__)


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    user_data = context.user_data or {}
    return user_data.get("lang") or context.bot_data.get("default_lang", "en")


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the /help command."""
    if update.message is None:
        logger.warning("help_command: missing message")
        return
    loc: Localizer = context.bot_data["localizer"]
    await update.message.reply_text(loc.t(_lang(context), "help_text"))
