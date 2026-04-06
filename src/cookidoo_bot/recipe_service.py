"""Use-case layer: orchestrates Cookidoo web client + AI adaptation."""

import logging
from dataclasses import dataclass

import aiohttp

from .ai_service import AdaptRequest, RecipeAIService
from .config import CookidooConfig
from .cookidoo_client import (
    CookidooWebClient,
    OriginalStep,
    RecipeSection,
    RecipeSections,
    iso8601_to_seconds,
)
from .i18n import lang_display
from .models import Step

logger = logging.getLogger(__name__)

_SEP = "\u2500\u2500"  # ── — section separator prefix/suffix
_SEP_PREFIX = f"{_SEP} "


def _ingr_with_sections(
    flat: list[str],
    sections: list[RecipeSection],
) -> list[str]:
    """Interleave section-separator strings into the flat ingredient list.

    Only applied when the summed item counts match the flat list length.
    Sections without a name do not produce a separator line.
    """
    if not sections or sum(s.item_count for s in sections) != len(flat):
        return flat
    result: list[str] = []
    idx = 0
    for sec in sections:
        if sec.name:
            result.append(f"{_SEP} {sec.name} {_SEP}")
        result.extend(flat[idx : idx + sec.item_count])
        idx += sec.item_count
    return result


def _steps_with_sections(
    flat: list[OriginalStep],
    sections: list[RecipeSection],
) -> list[OriginalStep]:
    """Interleave separator OriginalStep entries into the flat step list.

    Only applied when the summed item counts match the flat list length.
    Sections without a name do not produce a separator step.
    """
    if not sections or sum(s.item_count for s in sections) != len(flat):
        return flat
    result: list[OriginalStep] = []
    idx = 0
    for sec in sections:
        if sec.name:
            result.append(OriginalStep(text=f"{_SEP} {sec.name} {_SEP}"))
        result.extend(flat[idx : idx + sec.item_count])
        idx += sec.item_count
    return result


def _extract_step_sections(
    steps: list[OriginalStep],
) -> tuple[list[OriginalStep], list[tuple[int, str]]]:
    """Split section-separator steps out of a step list.

    Returns (real_steps, insertions) where insertions is a list of
    (before_index_in_real_steps, separator_text) pairs recording where
    each separator should be re-inserted after Gemini processes the steps.
    """
    real: list[OriginalStep] = []
    insertions: list[tuple[int, str]] = []
    for step in steps:
        if step.text.startswith(_SEP_PREFIX):
            insertions.append((len(real), step.text))
        else:
            real.append(step)
    return real, insertions


def _reinsert_step_sections(
    adapted_steps: list[Step],
    insertions: list[tuple[int, str]],
) -> list[Step]:
    """Re-insert separator Step objects into Gemini-adapted steps.

    Iterates in reverse so earlier insertions do not shift later indices.
    """
    result: list[Step] = list(adapted_steps)
    for pos, text in reversed(insertions):
        result.insert(pos, Step(text=text))
    return result


def _extract_ingr_sections(
    ingredients: list[str],
) -> tuple[list[str], list[tuple[int, str]]]:
    """Split section-separator strings out of a flat ingredient list.

    Returns (real_ingredients, insertions) following the same convention
    as _extract_step_sections.
    """
    real: list[str] = []
    insertions: list[tuple[int, str]] = []
    for item in ingredients:
        if item.startswith(_SEP_PREFIX):
            insertions.append((len(real), item))
        else:
            real.append(item)
    return real, insertions


def _reinsert_ingr_sections(
    adapted: list[str],
    insertions: list[tuple[int, str]],
) -> list[str]:
    """Re-insert separator strings into Gemini-adapted ingredients.

    Iterates in reverse so earlier insertions do not shift later indices.
    """
    result: list[str] = list(adapted)
    for pos, text in reversed(insertions):
        result.insert(pos, text)
    return result


def _apply_alternatives(
    flat: list[str],
    alternatives: list[str | None],
) -> list[str]:
    """Append alternative text to each ingredient that has one.

    Only applied when the alternatives list length matches the flat list.
    Format: "<main> / <alternative>"
    """
    if not alternatives or len(alternatives) != len(flat):
        return flat
    return [
        f"{ing} / {alt}" if alt else ing
        for ing, alt in zip(flat, alternatives, strict=False)
    ]


def _apply_translated_names(
    insertions: list[tuple[int, str]],
    translated: list[str],
) -> list[tuple[int, str]]:
    """Replace section names in separator tuples with translated versions.

    Only applied when the translated list length matches the insertions list.
    """
    if not translated or len(translated) != len(insertions):
        return insertions
    return [
        (pos, f"{_SEP} {name} {_SEP}")
        for (pos, _), name in zip(insertions, translated, strict=False)
    ]


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

            # Fetch section structure from the ORIGINAL recipe page using the
            # authenticated session — section metadata is lost after cloning.
            try:
                sections = await client.get_recipe_sections(recipe_url)
                logger.info(
                    "Original sections: %d ingredient, %d step",
                    len(sections.ingredient_sections),
                    len(sections.step_sections),
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not parse original recipe sections;"
                    " section separators will be skipped"
                )
                sections = RecipeSections(
                    ingredient_sections=[],
                    step_sections=[],
                )

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
                # Fetch TTS steps from the copy's edit page (sections are
                # already captured above from the original URL).
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

                structured_ingredients = _ingr_with_sections(
                    _apply_alternatives(
                        rc.get("recipeIngredient") or [],
                        sections.ingredient_alternatives,
                    ),
                    sections.ingredient_sections,
                )
                clean_ingredients, ingr_insertions = _extract_ingr_sections(
                    structured_ingredients
                )

                named_ingr_names = [
                    s.name for s in sections.ingredient_sections if s.name
                ]
                named_step_names = [
                    s.name for s in sections.step_sections if s.name
                ]

                # Inject section separators, then strip them out before
                # sending to Gemini; they are re-inserted afterwards so
                # the Cookidoo PATCH receives them at the right positions.
                source_steps = _steps_with_sections(
                    source_steps, sections.step_sections
                )
                clean_steps, step_insertions = _extract_step_sections(
                    source_steps
                )

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
                        ingredients=clean_ingredients,
                        source_steps=clean_steps,
                        servings_changed=servings is not None,
                        translate_to=translate_to,
                        ingredient_section_names=named_ingr_names,
                        step_section_names=named_step_names,
                    )
                )

                # Re-inject section separators at their original positions,
                # using translated names from the Gemini response.
                ingr_insertions = _apply_translated_names(
                    ingr_insertions, adapted.ingredient_section_names
                )
                step_insertions = _apply_translated_names(
                    step_insertions, adapted.step_section_names
                )
                adapted.ingredients = _reinsert_ingr_sections(
                    adapted.ingredients, ingr_insertions
                )
                adapted.instructions = _reinsert_step_sections(
                    adapted.instructions, step_insertions
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
