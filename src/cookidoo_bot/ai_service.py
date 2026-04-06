"""AI service: calls Gemini to adapt and/or translate a recipe."""

import re

from google import genai

from .config import GoogleConfig
from .cookidoo_client import OriginalStep, OriginalTTS
from .models import AdaptedRecipe

_TTS_PH_RE = re.compile(r"⟦TTS_(\d+)⟧")


def _mark_tts(text: str, tts_list: list[OriginalTTS]) -> str:
    """Replace each TTS display text with a ⟦TTS_N⟧ placeholder (left-to-right)."""
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
    """Build the language-appropriate TTS display string from machine params."""
    speed_w = _SPEED_WORD.get(ui_lang, "vel")
    time_str = f"{tts.time} {tts.time_unit}"
    if tts.temperature:
        val = tts.temperature.get("value", "")
        if val.lower() == "varoma":
            return f"Varoma/{time_str}/{speed_w} {tts.speed}"
        return f"{time_str}/{val}°/{speed_w} {tts.speed}"
    return f"{time_str}/{speed_w} {tts.speed}"


def _build_instruction_payload(
    translated_text: str, tts_list: list[OriginalTTS], ui_lang: str
) -> dict:
    """Replace ⟦TTS_N⟧ placeholders in *translated_text* with language-formatted display
    strings, then build the offset-based annotations dict for the Cookidoo PATCH API.
    """
    text = translated_text
    annotations: list[dict] = []
    # Collect all matches on the ORIGINAL text; process left-to-right and track shift.
    offset_shift = 0
    for m in _TTS_PH_RE.finditer(translated_text):
        idx = int(m.group(1))
        if idx >= len(tts_list):
            continue
        tts = tts_list[idx]
        display = _format_tts_display(tts, ui_lang)
        placeholder = f"⟦TTS_{idx}⟧"
        adj_start = m.start() + offset_shift
        # Safety: verify the placeholder is still at the expected position
        if text[adj_start : adj_start + len(placeholder)] != placeholder:
            adj_start = text.find(placeholder)
            if adj_start == -1:
                continue
        text = (
            text[:adj_start] + display + text[adj_start + len(placeholder) :]
        )
        offset_shift += len(display) - len(placeholder)
        data: dict = {"speed": tts.speed, "time": tts.time}
        if tts.temperature:
            data["temperature"] = tts.temperature
        annotations.append(
            {
                "type": "TTS",
                "data": data,
                "position": {"offset": adj_start, "length": len(display)},
            }
        )
    return {"type": "STEP", "text": text, "annotations": annotations}


class RecipeAIService:
    """Calls Gemini to produce an adapted/translated AdaptedRecipe."""

    def __init__(self, client: genai.Client, cfg: GoogleConfig) -> None:
        self._client = client
        self._cfg = cfg

    async def adapt(
        self,
        *,
        recipe_name: str,
        orig_servings: int,
        target_servings: int,
        total_time_s: int,
        prep_time_s: int,
        ingredients: list[str],
        source_steps: list[OriginalStep],
        servings_changed: bool,
        translate_to: str | None,
    ) -> AdaptedRecipe:
        task_parts: list[str] = []
        if servings_changed:
            task_parts.append(
                f"Adapt all ingredient quantities from {orig_servings} to {target_servings} servings."
            )
        if translate_to:
            task_parts.append(
                f"Translate everything (name, hints, ingredients, instructions) to {translate_to}."
            )

        marked_steps = [_mark_tts(s.text, s.tts_list) for s in source_steps]

        tts_note = ""
        if any(s.tts_list for s in source_steps):
            tts_note = (
                "\n\nIMPORTANT: Steps containing ⟦TTS_N⟧ placeholders mark exact positions "
                "of Thermomix machine operations. Preserve each placeholder EXACTLY as-is "
                "(⟦TTS_0⟧, ⟦TTS_1⟧, …) at the correct grammatical position in your output. "
                "Do NOT translate, remove, or modify them in any way."
            )

        prompt = (
            "\n".join(task_parts) + "\n\n"
            f"Recipe: {recipe_name}\n"
            f"Original servings: {orig_servings} → target: {target_servings}\n"
            f"Original totalTime: {total_time_s} s, prepTime: {prep_time_s} s\n\n"
            "Ingredients:\n"
            + "\n".join(ingredients)
            + "\n\nInstructions:\n"
            + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(marked_steps))
            + tts_note
        )

        response = await self._client.aio.models.generate_content(
            model=self._cfg.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": AdaptedRecipe.model_json_schema(),
                "thinking_config": {
                    "thinking_level": self._cfg.thinking_level
                },
            },
        )
        return AdaptedRecipe.model_validate_json(response.text)

    @staticmethod
    def to_cookidoo_payloads(
        adapted: AdaptedRecipe,
        final_servings: int,
        source_steps: list[OriginalStep],
        ui_lang: str,
    ) -> list[dict]:
        """Return ordered list of PATCH payloads to send to the Cookidoo API."""
        instructions = [
            _build_instruction_payload(
                step_text,
                source_steps[i].tts_list if i < len(source_steps) else [],
                ui_lang,
            )
            for i, step_text in enumerate(adapted.instructions)
        ]
        return [
            {
                "totalTime": adapted.totalTime,
                "prepTime": adapted.prepTime,
                "yield": {"value": final_servings, "unitText": "portion"},
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
