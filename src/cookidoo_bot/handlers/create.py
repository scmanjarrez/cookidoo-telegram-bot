"""/ create conversation handler."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

if TYPE_CHECKING:
    from cookidoo_bot.i18n import Localizer
    from cookidoo_bot.recipe_service import RecipeService

logger = logging.getLogger(__name__)

# ─── Conversation states ─────────────────────────────────────────────────

(
    ASK_URL,
    ASK_ADAPT_SERVINGS,
    ASK_SERVINGS,
    ASK_TRANSLATE,
) = range(4)

# ─── Constants ──────────────────────────────────────────────────────────────

_MIN_CO_UK_PARTS = 3  # hostname parts for 'co.uk' style domains

_COOKIDOO_URL_RE = re.compile(
    r"https?://cookidoo\.[a-z.]+/recipes/recipe/([a-zA-Z-]+)/([a-zA-Z0-9]+)"
)

# ─── Helpers ────────────────────────────────────────────────────────────────


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    user_data = context.user_data or {}
    return user_data.get("lang") or context.bot_data.get("default_lang", "en")


def _t(context: ContextTypes.DEFAULT_TYPE, key: str, **kwargs: object) -> str:
    loc: Localizer = context.bot_data["localizer"]
    return loc.t(_lang(context), key, **kwargs)


def _esc(s: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", s)


def _parse_cookidoo_url(url: str) -> tuple[str, str, str, str] | None:
    """Return (recipe_id, country_code, language, foundation_url) or None."""
    m = _COOKIDOO_URL_RE.search(url)
    if not m:
        return None
    language = m.group(1)
    recipe_id = m.group(2)
    hostname = urlparse(url).hostname or ""
    parts = hostname.split(".")
    if "international" in parts:
        country_code = "international"
    elif len(parts) >= _MIN_CO_UK_PARTS and parts[-2] == "co":
        country_code = "co.uk"
    else:
        country_code = parts[-1]
    foundation_url = f"https://{hostname}/foundation/{language}"
    return recipe_id, country_code, language, foundation_url


def _yes_no_kb(context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[_t(context, "yes_label"), _t(context, "no_label")]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


def _is_yes(text: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return text.strip().lower() == _t(context, "yes_label").lower()


def _is_no(text: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return text.strip().lower() == _t(context, "no_label").lower()


def _parse_servings(text: str) -> int:
    """Parse and validate a positive servings count from user input."""
    n = int(text)
    if n < 1:
        raise ValueError
    return n


# ─── Handlers ──────────────────────────────────────────────────────────────


async def create_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Start the /create conversation flow."""
    if update.message is None or update.effective_user is None:
        logger.warning("create_start: missing message or user")
        return ConversationHandler.END
    await update.message.reply_text(_t(context, "ask_url"))
    return ASK_URL


async def receive_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate and store the Cookidoo recipe URL."""
    if update.message is None or update.message.text is None:
        logger.warning("receive_url: missing message or text")
        return ConversationHandler.END
    if context.user_data is None:
        await update.message.reply_text(
            _t(context, "error_unexpected", error="session not initialised")
        )
        return ConversationHandler.END
    parsed = _parse_cookidoo_url(update.message.text.strip())
    if parsed is None:
        await update.message.reply_text(_t(context, "invalid_url"))
        return ASK_URL
    recipe_id, country_code, recipe_language, foundation_url = parsed
    context.user_data.update(
        original_url=update.message.text.strip(),
        recipe_id=recipe_id,
        country_code=country_code,
        recipe_language=recipe_language,
        foundation_url=foundation_url,
    )
    await update.message.reply_text(
        _t(context, "url_received", recipe_id=recipe_id),
        reply_markup=_yes_no_kb(context),
    )
    return ASK_ADAPT_SERVINGS


async def receive_adapt_servings_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle the 'adapt servings?' yes/no choice."""
    if update.message is None or update.message.text is None:
        logger.warning(
            "receive_adapt_servings_choice: missing message or text"
        )
        return ConversationHandler.END
    if context.user_data is None:
        await update.message.reply_text(
            _t(context, "error_unexpected", error="session not initialised")
        )
        return ConversationHandler.END
    text = update.message.text.strip()
    if not (_is_yes(text, context) or _is_no(text, context)):
        await update.message.reply_text(
            _t(context, "invalid_yes_no"), reply_markup=_yes_no_kb(context)
        )
        return ASK_ADAPT_SERVINGS
    if _is_yes(text, context):
        await update.message.reply_text(
            _t(context, "ask_servings"), reply_markup=ReplyKeyboardRemove()
        )
        return ASK_SERVINGS
    context.user_data["servings"] = None
    await update.message.reply_text(
        _t(context, "ask_translate", language=_t(context, "language_name")),
        reply_markup=_yes_no_kb(context),
    )
    return ASK_TRANSLATE


async def receive_servings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Parse and store the target servings count."""
    if update.message is None or update.message.text is None:
        logger.warning("receive_servings: missing message or text")
        return ConversationHandler.END
    if context.user_data is None:
        await update.message.reply_text(
            _t(context, "error_unexpected", error="session not initialised")
        )
        return ConversationHandler.END
    try:
        servings = _parse_servings(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(_t(context, "invalid_servings"))
        return ASK_SERVINGS
    context.user_data["servings"] = servings
    await update.message.reply_text(
        _t(context, "ask_translate", language=_t(context, "language_name")),
        reply_markup=_yes_no_kb(context),
    )
    return ASK_TRANSLATE


async def receive_translate_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle the 'translate?' yes/no choice and trigger processing."""
    if update.message is None or update.message.text is None:
        logger.warning("receive_translate_choice: missing message or text")
        return ConversationHandler.END
    if context.user_data is None:
        await update.message.reply_text(
            _t(context, "error_unexpected", error="session not initialised")
        )
        return ConversationHandler.END
    text = update.message.text.strip()
    if not (_is_yes(text, context) or _is_no(text, context)):
        await update.message.reply_text(
            _t(context, "invalid_yes_no"), reply_markup=_yes_no_kb(context)
        )
        return ASK_TRANSLATE
    context.user_data["should_translate"] = _is_yes(text, context)
    await _do_process(update, context)
    return ConversationHandler.END


async def _do_process(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if update.message is None or update.effective_chat is None:
        logger.warning("_do_process: missing message or chat")
        return
    if context.user_data is None:
        await update.message.reply_text(
            _t(context, "error_unexpected", error="session not initialised")
        )
        return
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        _t(context, "processing"), reply_markup=ReplyKeyboardRemove()
    )

    async def _keep_typing() -> None:
        """Send 'typing' action every 4 s until cancelled."""
        while True:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(_keep_typing())
    try:
        service: RecipeService = context.bot_data["recipe_service"]
        result = await service.create_and_adapt(
            recipe_url=context.user_data["original_url"],
            servings=context.user_data.get("servings"),
            ui_lang=_lang(context),
            should_translate=context.user_data.get("should_translate", False),
        )
        if result.adapted:
            n = _esc(result.recipe_name)
            s = _esc(str(result.final_servings))
            lbl = _esc(_t(context, "result_view_recipe"))
            reply = (
                f"\u2705 *{n}*"
                f" \u2014 {s} servings\n\n"
                f"\U0001f517 [{lbl}]({result.recipe_url})"
            )
        else:
            n = _esc(result.recipe_name)
            lbl = _esc(_t(context, "result_view_recipe"))
            reply = f"\u2705 *{n}*\n\n\U0001f517 [{lbl}]({result.recipe_url})"
        await update.message.reply_text(
            reply, parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as exc:
        logger.exception("Unexpected error processing recipe")
        await update.message.reply_text(
            _t(context, "error_unexpected", error=exc)
        )
    finally:
        typing_task.cancel()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current /create conversation."""
    if update.message is None:
        logger.warning("cancel: missing message")
        return ConversationHandler.END
    if context.user_data is None:
        await update.message.reply_text(
            _t(context, "error_unexpected", error="session not initialised")
        )
        return ConversationHandler.END
    await update.message.reply_text(
        _t(context, "cancelled"), reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END


# ─── Handler registration ──────────────────────────────────────────────────


def build_conv_handler() -> ConversationHandler:
    """Build and return the ConversationHandler for /create."""
    return ConversationHandler(
        entry_points=[CommandHandler("create", create_start)],
        states={
            ASK_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)
            ],
            ASK_ADAPT_SERVINGS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_adapt_servings_choice,
                )
            ],
            ASK_SERVINGS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, receive_servings
                )
            ],
            ASK_TRANSLATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, receive_translate_choice
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
