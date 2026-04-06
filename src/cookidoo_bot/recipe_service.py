"""Use-case layer: orchestrates Cookidoo web client + AI adaptation."""

import logging
from dataclasses import dataclass

import aiohttp

from .ai_service import AdaptRequest, RecipeAIService
from .config import CookidooConfig
from .cookidoo_client import (
    CookidooWebClient,
    OriginalStep,
    iso8601_to_seconds,
)
from .i18n import lang_display

logger = logging.getLogger(__name__)


@dataclass
class RecipeResult:
    """Result returned by a successful create-and-adapt operation."""

    recipe_id: str
    recipe_name: str
    recipe_url: str
    final_servings: int
    adapted: bool


class RecipeService:
    """Orchestrates Cookidoo recipe cloning and AI adaptation."""

    def __init__(
        self, cookidoo_cfg: CookidooConfig, ai: RecipeAIService
    ) -> None:
        """Initialize with Cookidoo config and an AI service instance."""
        self._cookidoo_cfg = cookidoo_cfg
        self._ai = ai

    async def create_and_adapt(
        self,
        recipe_url: str,
        servings: int | None,
        ui_lang: str,
        *,
        should_translate: bool,
    ) -> RecipeResult:
        """Clone a Cookidoo recipe and optionally adapt/translate it."""
        translate_to = lang_display(ui_lang) if should_translate else None
        should_adapt = servings is not None or should_translate

        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as session:
            client = CookidooWebClient(
                session,
                site=self._cookidoo_cfg.site,
                username=self._cookidoo_cfg.username,
                password=self._cookidoo_cfg.password,
            )
            await client.login()

            data = await client.add_custom_recipe(recipe_url)
            recipe_id: str = data["recipeId"]
            rc: dict = data["recipeContent"]
            orig_servings: int = (rc.get("recipeYield") or {}).get(
                "value"
            ) or 1
            final_servings = (
                servings if servings is not None else orig_servings
            )
            recipe_name: str = rc.get("name") or recipe_id

            if should_adapt:
                # Fetch the step TTS structure from the edit page
                try:
                    source_steps = await client.get_original_steps(recipe_id)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Could not parse edit-page steps;"
                        " TTS annotations will be skipped"
                    )
                    source_steps = [
                        OriginalStep(text=s)
                        for s in (rc.get("recipeInstructions") or [])
                    ]

                adapted = await self._ai.adapt(
                    AdaptRequest(
                        recipe_name=rc.get("name") or "",
                        orig_servings=orig_servings,
                        target_servings=final_servings,
                        total_time_s=iso8601_to_seconds(
                            rc.get("totalTime") or ""
                        ),
                        prep_time_s=iso8601_to_seconds(
                            rc.get("prepTime") or ""
                        ),
                        ingredients=rc.get("recipeIngredient") or [],
                        source_steps=source_steps,
                        servings_changed=servings is not None,
                        translate_to=translate_to,
                    )
                )
                for payload in RecipeAIService.to_cookidoo_payloads(
                    adapted, final_servings, source_steps, ui_lang
                ):
                    await client.patch_recipe(recipe_id, payload)
                recipe_name = adapted.name or recipe_name

            return RecipeResult(
                recipe_id=recipe_id,
                recipe_name=recipe_name,
                recipe_url=client.recipe_url(recipe_id),
                final_servings=final_servings,
                adapted=should_adapt,
            )
