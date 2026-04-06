"""Pydantic models for structured Gemini output."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ─── Temperature Literal types ───────────────────────────────────────────────

BrowningTemperature = Literal["140", "145", "150", "155", "160"]

WarmUpTemperature = Literal[
    "37",
    "40",
    "45",
    "50",
    "55",
    "60",
    "65",
    "70",
    "75",
    "80",
    "85",
    "90",
]

ManualTemperature = Literal[
    "37",
    "40",
    "45",
    "50",
    "55",
    "60",
    "65",
    "70",
    "75",
    "80",
    "85",
    "90",
    "95",
    "98",
    "100",
    "105",
    "110",
    "115",
    "120",
]

# ─── Speed Literal types ─────────────────────────────────────────────────────

SteamingSpeed = Literal[
    "soft",
    "0.5",
    "1",
    "1.5",
    "2",
    "2.5",
    "3",
    "3.5",
    "4",
    "4.5",
    "5",
]

BlendSpeed = Literal["6", "6.5", "7", "7.5", "8"]

WarmUpSpeed = Literal["soft", "1", "2"]

ManualSpeed = Literal[
    "soft",
    "0.5",
    "1",
    "1.5",
    "2",
    "2.5",
    "3",
    "3.5",
    "4",
    "4.5",
    "5",
    "5.5",
    "6",
    "6.5",
    "7",
    "7.5",
    "8",
    "8.5",
    "9",
    "9.5",
    "10",
]

# ─── Ingredient reference ────────────────────────────────────────────────────


class IngredientRef(BaseModel):
    """Links a step text alias to the full ingredient description."""

    alias: str = Field(
        description=(
            "Exact span of text as it appears in the step. "
            "Prefer a short, natural alias "
            "(e.g. 'the pork', 'la carne') over the full name."
        )
    )
    description: str = Field(
        description=(
            "Full ingredient description copied verbatim "
            "from the ingredients list."
        )
    )


# ─── Thermomix mode annotations ──────────────────────────────────────────────


class BrowningMode(BaseModel):
    """Browning / Dorar mode - sears ingredients in the bowl."""

    name: Literal["browning"] = Field(
        default="browning",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'browning'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text activating this mode "
            "(e.g. 'Dorar', 'browning')."
        )
    )
    temperature: BrowningTemperature = Field(
        description="Browning temperature in C: 140-160 in steps of 5."
    )
    minutes: int = Field(ge=0, description="Browning duration, whole minutes.")
    seconds: int = Field(
        ge=0,
        le=59,
        description="Browning duration, remaining seconds (0-59).",
    )
    power: Literal["Intense", "Gentle"] = Field(
        description=(
            "'Intense' for high-power browning, "
            "'Gentle' for lower-power / finishing."
        )
    )

    def api_data(self) -> dict[str, object]:
        """Return Cookidoo PATCH data dict for this browning operation."""
        return {
            "temperature": {"value": self.temperature, "unit": "C"},
            "time": self.minutes * 60 + self.seconds,
            "power": self.power,
        }


class DoughMode(BaseModel):
    """Dough / Knead mode - Amasar."""

    name: Literal["dough"] = Field(
        default="dough",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'dough'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text activating kneading "
            "(e.g. 'Amasar', 'knead')."
        )
    )
    minutes: int = Field(ge=0, description="Kneading duration, whole minutes.")
    seconds: int = Field(
        ge=0,
        le=59,
        description="Kneading duration, remaining seconds (0-59).",
    )

    def api_data(self) -> dict[str, object]:
        """Return Cookidoo PATCH data dict for this kneading operation."""
        return {"time": self.minutes * 60 + self.seconds}


class TurboMode(BaseModel):
    """Turbo pulse mode - short high-speed bursts."""

    name: Literal["turbo"] = Field(
        default="turbo",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'turbo'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text for Turbo (e.g. 'Turbo')."
        )
    )
    pulse_seconds: Literal["0.5", "1.0", "2.0"] = Field(
        description="Duration of each pulse in seconds: 0.5, 1, or 2."
    )
    pulse_count: int = Field(
        ge=1, le=9, description="Number of turbo pulses (1-9)."
    )

    def api_data(self) -> dict[str, object]:
        """Return Cookidoo PATCH data dict for this turbo operation."""
        return {"time": self.pulse_seconds, "pulseCount": self.pulse_count}


class SteamingMode(BaseModel):
    """Steaming / Al vapor mode - cooks with a steam accessory."""

    name: Literal["steaming"] = Field(
        default="steaming",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'steaming'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text for steaming "
            "(e.g. 'Al vapor', 'Varoma')."
        )
    )
    speed: SteamingSpeed = Field(
        description="Mixer speed: 'soft' or 0.5-5 in steps of 0.5."
    )
    direction: Literal["CW", "CCW"] = Field(
        description=(
            "Blade direction: 'CW' (clockwise) for normal stirring, "
            "'CCW' (counter-clockwise) for delicate items."
        )
    )
    minutes: int = Field(ge=0, description="Steaming duration, whole minutes.")
    seconds: int = Field(
        ge=0,
        le=59,
        description="Steaming duration, remaining seconds (0-59).",
    )
    accessory: Literal[
        "SimmeringBasket",
        "Varoma",
        "VaromaAndSimmeringBasket",
    ] = Field(
        description=(
            "Steam accessory: 'SimmeringBasket', 'Varoma', "
            "or 'VaromaAndSimmeringBasket'."
        )
    )

    def api_data(self) -> dict[str, object]:
        """Return Cookidoo PATCH data dict for this steaming operation."""
        return {
            "speed": self.speed,
            "direction": self.direction,
            "time": self.minutes * 60 + self.seconds,
            "accessory": self.accessory,
        }


class BlendMode(BaseModel):
    """Blend / Triturar mode - high-speed blending."""

    name: Literal["blend"] = Field(
        default="blend",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'blend'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text for blending "
            "(e.g. 'Triturar', 'blend')."
        )
    )
    speed: BlendSpeed = Field(
        description="Blending speed: 6 to 8 in steps of 0.5."
    )
    minutes: int = Field(ge=0, description="Blending duration, whole minutes.")
    seconds: int = Field(
        ge=0,
        le=59,
        description="Blending duration, remaining seconds (0-59).",
    )

    def api_data(self) -> dict[str, object]:
        """Return Cookidoo PATCH data dict for this blending operation."""
        return {
            "speed": self.speed,
            "time": self.minutes * 60 + self.seconds,
        }


class WarmUpMode(BaseModel):
    """Warm-up / Calentar mode - heats liquid to a target temperature."""

    name: Literal["warm_up"] = Field(
        default="warm_up",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'warm_up'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text for warm-up "
            "(e.g. 'Calentar')."
        )
    )
    speed: WarmUpSpeed = Field(
        description="Stirring speed: 'soft', '1', or '2'."
    )
    temperature: WarmUpTemperature = Field(
        description="Target temperature in C: 37, or 40-90 in steps of 5."
    )

    def api_data(self) -> dict[str, object]:
        """Return Cookidoo PATCH data dict for this warm-up operation."""
        return {
            "speed": self.speed,
            "temperature": {"value": self.temperature, "unit": "C"},
        }


class RiceCookerMode(BaseModel):
    """Rice cooker / Coccion de arroz mode - automated rice program."""

    name: Literal["rice_cooker"] = Field(
        default="rice_cooker",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'rice_cooker'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text for rice-cooker mode "
            "(e.g. 'Coccion de arroz', 'rice cooker')."
        )
    )

    def api_data(self) -> dict[str, object]:
        """Return empty Cookidoo PATCH data dict (no params)."""
        return {}


class ManualMode(BaseModel):
    """Manual / TTS mode - free-form time + speed + temperature operation."""

    name: Literal["manual"] = Field(
        default="manual",
        description=(
            "Fixed English API identifier. "
            "ALWAYS 'manual'. NEVER translate this field."
        ),
    )
    keyword: str = Field(
        description=(
            "Exact word or phrase in the step text marking "
            "this machine operation."
        )
    )
    speed: ManualSpeed = Field(
        description="Blade speed: 'soft', or 0.5 to 10 in steps of 0.5."
    )
    direction: Literal["CW", "CCW"] = Field(
        description=(
            "Blade direction: 'CW' (clockwise, normal) or "
            "'CCW' (counter-clockwise, reverse)."
        )
    )
    minutes: int = Field(
        ge=0, description="Operation duration, whole minutes."
    )
    seconds: int = Field(
        ge=0,
        le=59,
        description="Operation duration, remaining seconds (0-59).",
    )
    temperature: ManualTemperature | None = Field(
        default=None,
        description=(
            "Optional temperature in C: None (no heating), "
            "37, or 40-120 in steps of 5 (also 98)."
        ),
    )

    def api_data(self) -> dict[str, object]:
        """Return TTS-style Cookidoo PATCH data dict."""
        data: dict[str, object] = {
            "speed": self.speed,
            "time": self.minutes * 60 + self.seconds,
        }
        if self.temperature is not None:
            data["temperature"] = {
                "value": self.temperature,
                "unit": "C",
            }
        return data


# ─── Discriminated union of all mode types ───────────────────────────────────

ModeAnnotation = Annotated[
    BrowningMode
    | DoughMode
    | TurboMode
    | SteamingMode
    | BlendMode
    | WarmUpMode
    | RiceCookerMode
    | ManualMode,
    Field(discriminator="name"),
]

# ─── Step ────────────────────────────────────────────────────────────────────


class Step(BaseModel):
    """A preparation step with ingredient references and machine-mode links."""

    text: str = Field(
        description=(
            "Full step instruction text. "
            "Preserve ALL ⟦TTS_N⟧ placeholders EXACTLY as-is at the "
            "grammatically correct position. Do NOT translate, remove, "
            "or modify them. Ingredient aliases and mode keywords MUST "
            "appear verbatim within this text."
        )
    )
    ingredient_refs: list[IngredientRef] = Field(
        default_factory=list,
        description=(
            "Every ingredient mentioned in this step. "
            "alias = exact text span; "
            "description = full matching ingredient line."
        ),
    )
    mode_annotations: list[ModeAnnotation] = Field(
        default_factory=list,
        description=(
            "Thermomix cooking modes activated in this step. "
            "One entry per activation. "
            "keyword = exact word/phrase as written in the step text."
        ),
    )


# ─── Top-level recipe ────────────────────────────────────────────────────────


class AdaptedRecipe(BaseModel):
    """Full adapted and/or translated recipe ready for Cookidoo PATCH."""

    name: str = Field(description="Recipe name")
    hints: str = Field(
        description=(
            "Cooking tips and suggestions, "
            "paragraphs separated by double newline"
        )
    )
    total_time: int = Field(
        alias="totalTime",
        description="Total recipe time in seconds",
    )
    prep_time: int = Field(
        alias="prepTime",
        description="Active preparation time in seconds",
    )
    ingredients: list[str] = Field(
        description=(
            "Ingredient list, one string per ingredient "
            "including quantity and unit"
        )
    )
    instructions: list[Step] = Field(
        description="Preparation steps as structured Step objects"
    )
