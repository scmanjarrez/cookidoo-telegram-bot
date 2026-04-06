"""Pydantic models for structured Gemini output."""

from pydantic import BaseModel, Field


class AdaptedRecipe(BaseModel):
    name: str = Field(description="Recipe name")
    hints: str = Field(
        description="Cooking tips and suggestions, paragraphs separated by double newline"
    )
    totalTime: int = Field(description="Total recipe time in seconds")
    prepTime: int = Field(description="Active preparation time in seconds")
    ingredients: list[str] = Field(
        description="Ingredient list, one string per ingredient including quantity and unit"
    )
    instructions: list[str] = Field(
        description=(
            "Preparation steps as plain text strings. "
            "Each step may contain ⟦TTS_0⟧, ⟦TTS_1⟧, … placeholders at the positions "
            "of Thermomix machine operations. "
            "Preserve ALL such placeholders EXACTLY as-is at the grammatically correct "
            "position — do NOT translate, remove, or modify them in any way."
        )
    )
