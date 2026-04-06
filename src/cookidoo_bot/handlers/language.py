"""/language command handler."""

from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from cookidoo_bot.i18n import Localizer


def _localizer(context: ContextTypes.DEFAULT_TYPE) -> Localizer:
    return context.bot_data["localizer"]


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang") or context.bot_data.get(
        "default_lang", "en"
    )


async def set_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    localizer = _localizer(context)
    lang = _lang(context)
    available = localizer.available()

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
    lang_path.write_text(code)
    context.bot_data["default_lang"] = code
    context.user_data["lang"] = code

    await update.message.reply_text(
        localizer.t(code, "language_set", language=code)
    )
