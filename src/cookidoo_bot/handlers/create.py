"""/create conversation handler."""

import logging
import re
from urllib.parse import urlparse

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from cookidoo_bot.i18n import Localizer, lang_display
from cookidoo_bot.recipe_service import RecipeService

logger = logging.getLogger(__name__)

# ─── Conversation states ──────────────────────────────────────────────────────

(
    ASK_URL,
    ASK_ADAPT_SERVINGS,
    ASK_SERVINGS,
    ASK_TRANSLATE,
) = range(4)

# ─── Constants ────────────────────────────────────────────────────────────────

YES_NO_KB = ReplyKeyboardMarkup(
    [["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True
)

_COOKIDOO_URL_RE = re.compile(
    r"https?://cookidoo\.[a-z.]+/recipes/recipe/([a-zA-Z-]+)/([a-zA-Z0-9]+)"
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang") or context.bot_data.get(
        "default_lang", "en"
    )


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
    elif len(parts) >= 3 and parts[-2] == "co":
        country_code = "co.uk"
    else:
        country_code = parts[-1]
    foundation_url = f"https://{hostname}/foundation/{language}"
    return recipe_id, country_code, language, foundation_url


def _is_yes(text: str) -> bool:
    return text.strip().lower() in ("yes", "y")


def _is_no(text: str) -> bool:
    return text.strip().lower() in ("no", "n")


# ─── Handlers ────────────────────────────────────────────────────────────────


async def create_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    admin_id: int = context.bot_data["config"].telegram.admin_id
    if update.effective_user.id != admin_id:
        await update.message.reply_text(_t(context, "not_authorised"))
        return ConversationHandler.END
    await update.message.reply_text(_t(context, "ask_url"))
    return ASK_URL


async def receive_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        reply_markup=YES_NO_KB,
    )
    return ASK_ADAPT_SERVINGS


async def receive_adapt_servings_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    if not (_is_yes(text) or _is_no(text)):
        await update.message.reply_text(
            _t(context, "invalid_yes_no"), reply_markup=YES_NO_KB
        )
        return ASK_ADAPT_SERVINGS
    if _is_yes(text):
        await update.message.reply_text(
            _t(context, "ask_servings"), reply_markup=ReplyKeyboardRemove()
        )
        return ASK_SERVINGS
    context.user_data["servings"] = None
    await update.message.reply_text(
        _t(context, "ask_translate", language=lang_display(_lang(context))),
        reply_markup=YES_NO_KB,
    )
    return ASK_TRANSLATE


async def receive_servings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    try:
        servings = int(update.message.text.strip())
        if servings < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(_t(context, "invalid_servings"))
        return ASK_SERVINGS
    context.user_data["servings"] = servings
    await update.message.reply_text(
        _t(context, "ask_translate", language=lang_display(_lang(context))),
        reply_markup=YES_NO_KB,
    )
    return ASK_TRANSLATE


async def receive_translate_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text.strip()
    if not (_is_yes(text) or _is_no(text)):
        await update.message.reply_text(
            _t(context, "invalid_yes_no"), reply_markup=YES_NO_KB
        )
        return ASK_TRANSLATE
    context.user_data["should_translate"] = _is_yes(text)
    await _do_process(update, context)
    return ConversationHandler.END


async def _do_process(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.message.reply_text(
        _t(context, "processing"), reply_markup=ReplyKeyboardRemove()
    )
    try:
        service: RecipeService = context.bot_data["recipe_service"]
        result = await service.create_and_adapt(
            recipe_url=context.user_data["original_url"],
            servings=context.user_data.get("servings"),
            ui_lang=_lang(context),
            should_translate=context.user_data.get("should_translate", False),
        )
        if result.adapted:
            reply = (
                f"✅ *{_esc(result.recipe_name)}* — {_esc(str(result.final_servings))} servings\n\n"
                f"🔗 [{_esc(_t(context, 'result_view_recipe'))}]({result.recipe_url})"
            )
        else:
            reply = (
                f"✅ *{_esc(result.recipe_name)}*\n\n"
                f"🔗 [{_esc(_t(context, 'result_view_recipe'))}]({result.recipe_url})"
            )
        await update.message.reply_text(
            reply, parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as exc:
        logger.exception("Unexpected error processing recipe")
        await update.message.reply_text(
            _t(context, "error_unexpected", error=exc)
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        _t(context, "cancelled"), reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END


# ─── Handler registration ────────────────────────────────────────────────────


def build_conv_handler() -> ConversationHandler:
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
