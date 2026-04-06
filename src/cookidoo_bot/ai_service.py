"""AI service: calls Gemini to adapt and/or translate a recipe."""

import re
from dataclasses import dataclass
from dataclasses import field as dc_field

from google import genai

from .config import GoogleConfig
from .cookidoo_client import OriginalStep, OriginalTTS
from .models import AdaptedRecipe, ManualMode, Step

_TTS_PH_RE = re.compile(r"⟦TTS_(\d+)⟧")


def _mark_tts(text: str, tts_list: list[OriginalTTS]) -> str:
    """Replace TTS display text with ⟦TTS_N⟧ placeholders."""
    pos = 0
    for i, tts in enumerate(tts_list):
        found = text.find(tts.display_text, pos)
        if found == -1:
            continue
        marker = f"⟦TTS_{i}⟧"
        text = text[:found] + marker + text[found + len(tts.display_text) :]
        pos = found + len(marker)
    return text


_SPEED_WORD: dict[str, str] = {
    "es": "vel",
    "pt": "vel",
    "it": "vel",
    "de": "St.",
    "fr": "vit.",
    "nl": "stand",
    "en": "speed",
}


def _format_tts_display(tts: OriginalTTS, ui_lang: str) -> str:
    """Build the language-appropriate TTS display string."""
    speed_w = _SPEED_WORD.get(ui_lang, "vel")
    time_str = f"{tts.time} {tts.time_unit}"
    if tts.temperature:
        val = tts.temperature.get("value", "")
        if val.lower() == "varoma":
            return f"Varoma/{time_str}/{speed_w} {tts.speed}"
        return f"{time_str}/{val}\u00b0/{speed_w} {tts.speed}"
    return f"{time_str}/{speed_w} {tts.speed}"


def _apply_tts_placeholders(
    step_text: str,
    tts_list: list[OriginalTTS],
    ui_lang: str,
) -> tuple[str, list[dict[str, object]]]:
    """Expand ⟦TTS_N⟧ placeholders to display text; return annotations."""
    text = step_text
    annotations: list[dict[str, object]] = []
    offset_shift = 0
    for m in _TTS_PH_RE.finditer(step_text):
        idx = int(m.group(1))
        if idx >= len(tts_list):
            continue
        tts = tts_list[idx]
        display = _format_tts_display(tts, ui_lang)
        placeholder = f"⟦TTS_{idx}⟧"
        adj_start = m.start() + offset_shift
        if text[adj_start : adj_start + len(placeholder)] != placeholder:
            adj_start = text.find(placeholder)
            if adj_start == -1:
                continue
        text = (
            text[:adj_start] + display + text[adj_start + len(placeholder) :]
        )
        offset_shift += len(display) - len(placeholder)
        tts_data: dict[str, object] = {
            "speed": tts.speed,
            "time": tts.time,
        }
        if tts.temperature:
            tts_data["temperature"] = tts.temperature
        annotations.append(
            {
                "type": "TTS",
                "data": tts_data,
                "position": {
                    "offset": adj_start,
                    "length": len(display),
                },
            }
        )
    return text, annotations


def _build_step_payload(
    step: Step,
    tts_list: list[OriginalTTS],
    ui_lang: str,
) -> dict[str, object]:
    """Build offset-annotated PATCH payload for a single recipe step.

    1. Resolves ⟦TTS_N⟧ placeholders into TTS annotations.
    2. Adds INGREDIENT annotations for ingredient refs.
    3. Adds MODE (or TTS) annotations for mode activations.
    """
    text, annotations = _apply_tts_placeholders(step.text, tts_list, ui_lang)

    # Ingredient refs
    for ref in step.ingredient_refs:
        offset = text.find(ref.alias)
        if offset == -1:
            continue
        annotations.append(
            {
                "type": "INGREDIENT",
                "data": {"description": ref.description},
                "position": {
                    "offset": offset,
                    "length": len(ref.alias),
                },
            }
        )

    # Mode annotations
    for mode in step.mode_annotations:
        offset = text.find(mode.keyword)
        if offset == -1:
            continue
        pos = {"offset": offset, "length": len(mode.keyword)}
        if isinstance(mode, ManualMode):
            annotations.append(
                {
                    "type": "TTS",
                    "data": mode.api_data(),
                    "position": pos,
                }
            )
        else:
            annotations.append(
                {
                    "type": "MODE",
                    "name": mode.name,
                    "data": mode.api_data(),
                    "position": pos,
                }
            )

    return {"type": "STEP", "text": text, "annotations": annotations}


@dataclass
class AdaptRequest:
    """Parameters for a recipe adaptation request."""

    recipe_name: str
    orig_servings: int
    target_servings: int
    total_time_s: int
    prep_time_s: int
    ingredients: list[str]
    source_steps: list[OriginalStep]
    servings_changed: bool
    translate_to: str | None
    ingredient_section_names: list[str] = dc_field(default_factory=list)
    step_section_names: list[str] = dc_field(default_factory=list)
    original_hints: str | None = None


class RecipeAIService:
    """Calls Gemini to produce an adapted/translated AdaptedRecipe."""

    def __init__(self, client: genai.Client, cfg: GoogleConfig) -> None:
        """Initialize with a Gemini client and Google config."""
        self._client = client
        self._cfg = cfg

    async def adapt(self, req: AdaptRequest) -> AdaptedRecipe:
        """Adapt and/or translate a recipe using Gemini."""
        task_parts: list[str] = []
        if req.servings_changed:
            task_parts.append(
                f"Adapt all ingredient quantities"
                f" from {req.orig_servings}"
                f" to {req.target_servings} servings."
            )
        if req.translate_to:
            task_parts.append(
                f"Translate everything (name, ingredients,"
                f" instructions) to {req.translate_to}."
            )

        marked_steps = [
            _mark_tts(s.text, s.tts_list) for s in req.source_steps
        ]

        hints_note = ""
        if req.original_hints:
            if req.translate_to:
                hints_note = (
                    f"\n\nEXISTING HINTS (translate to {req.translate_to}):"
                    f"\n{req.original_hints}"
                )
            else:
                hints_note = (
                    "\n\nEXISTING HINTS (return exactly as provided):"
                    f"\n{req.original_hints}"
                )
        else:
            hints_note = (
                "\n\nHINTS: Generate 1-3 concise cooking tips for this"
                " recipe in the output language."
            )

        sections_note = ""
        if req.ingredient_section_names:
            sections_note += (
                "\n\nIngredient section names"
                " (translate to the target language if translating): "
                + ", ".join(req.ingredient_section_names)
            )
        if req.step_section_names:
            sections_note += (
                "\n\nStep section names"
                " (translate to the target language if translating): "
                + ", ".join(req.step_section_names)
            )

        tts_note = ""
        if any(s.tts_list for s in req.source_steps):
            tts_note = (
                "\n\nIMPORTANT - ⟦TTS_N⟧ PLACEHOLDERS:"
                " Steps containing ⟦TTS_N⟧ markers represent"
                " exact positions of Thermomix TTS operations"
                " from the original recipe."
                " Preserve each placeholder EXACTLY as-is"
                " (⟦TTS_0⟧, ⟦TTS_1⟧, ...) at the correct"
                " grammatical position in your output."
                " Do NOT translate, remove, or modify them."
            )

        annotation_guide = (
            "\n\nSTRUCTURED STEP ANNOTATIONS REQUIRED:"
            "\nFor mode_annotations, the 'name' field is a FIXED ENGLISH"
            " API identifier — NEVER translate it, always use the exact"
            " value listed. The 'keyword' field is the EXACT word or phrase"
            " as it appears in the recipe step text (can be any language)."
            "\n\nSupported modes:"
            "\n  name='browning'    keyword=word in text (e.g.'Dorar')"
            " → temperature (140|145|150|155|160 C),"
            " minutes, seconds 0-59, power (Intense|Gentle)"
            "\n  name='dough'       keyword=word in text (e.g.'Amasar')"
            " → minutes, seconds 0-59"
            "\n  name='turbo'       keyword=word in text (e.g.'Turbo')"
            " → pulse_seconds (0.5|1|2), pulse_count (1-9)"
            "\n  name='steaming'    keyword=word in text"
            " (e.g.'Al vapor','Varoma')"
            " → speed (soft|0.5..5 step 0.5), direction (CW|CCW),"
            " minutes, seconds 0-59,"
            " accessory (SimmeringBasket|Varoma"
            "|VaromaAndSimmeringBasket)"
            "\n  name='blend'       keyword=word in text (e.g.'Triturar')"
            " → speed (6|6.5|7|7.5|8), minutes, seconds 0-59"
            "\n  name='warm_up'     keyword=word in text (e.g.'Calentar')"
            " → speed (soft|1|2),"
            " temperature (37|40..90 step 5 C)"
            "\n  name='rice_cooker' keyword=word in text"
            " (e.g.'Coccion de arroz') → no extra fields"
            "\n  name='manual'      keyword=word in text"
            " → speed (soft|0.5..10 step 0.5), direction (CW|CCW),"
            " minutes, seconds 0-59,"
            " temperature (None|37|40..95|98|100..120 step 5 C)"
        )

        prompt = (
            "\n".join(task_parts) + "\n\n"
            f"Recipe: {req.recipe_name}\n"
            f"Original servings: {req.orig_servings}"
            f" \u2192 target: {req.target_servings}\n"
            f"Original totalTime: {req.total_time_s} s,"
            f" prepTime: {req.prep_time_s} s\n\n"
            "Ingredients:\n"
            + "\n".join(req.ingredients)
            + "\n\nInstructions:\n"
            + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(marked_steps))
            + hints_note
            + sections_note
            + tts_note
            + annotation_guide
        )

        response = await self._client.aio.models.generate_content(
            model=self._cfg.model,
            contents=prompt,
            config={  # type: ignore[arg-type]
                "response_mime_type": "application/json",
                "response_json_schema": AdaptedRecipe.model_json_schema(),
                "thinking_config": {
                    "thinking_level": self._cfg.thinking_level,
                },
            },
        )
        if response.text is None:
            msg = "Gemini returned an empty response"
            raise RuntimeError(msg)
        adapted = AdaptedRecipe.model_validate_json(response.text)
        # Gemini sometimes emits \\n (escaped backslash-n) in JSON strings
        # instead of an actual newline. Normalise before returning.
        adapted.hints = adapted.hints.replace("\\n", "\n")
        for step in adapted.instructions:
            step.text = step.text.replace("\\n", "\n")
        return adapted

    @staticmethod
    def to_cookidoo_payloads(
        adapted: AdaptedRecipe,
        final_servings: int,
        source_steps: list[OriginalStep],
        ui_lang: str,
    ) -> list[dict[str, object]]:
        """Return ordered list of PATCH payloads for the Cookidoo API."""
        instructions = [
            _build_step_payload(
                step,
                source_steps[i].tts_list if i < len(source_steps) else [],
                ui_lang,
            )
            for i, step in enumerate(adapted.instructions)
        ]
        return [
            {
                "totalTime": adapted.total_time,
                "prepTime": adapted.prep_time,
                "yield": {
                    "value": final_servings,
                    "unitText": "portion",
                },
            },
            {"name": adapted.name},
            {"hints": adapted.hints},
            {
                "ingredients": [
                    {"type": "INGREDIENT", "text": x}
                    for x in adapted.ingredients
                ]
            },
            {"instructions": instructions},
        ]
