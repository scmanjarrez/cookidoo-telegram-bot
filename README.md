# cookidoo-bot

> **Disclaimer:** This project was developed entirely with AI assistance
> (GitHub Copilot / Claude). Review the code carefully before running it
> with your own credentials.

A Telegram bot that clones any public Cookidoo recipe into your account and
uses Google Gemini to adapt quantities for a different number of servings
and/or translate the recipe into another language.

---

## Requirements

| Tool | Version |
|------|---------|
| Python | ≥ 3.12 |
| [uv](https://docs.astral.sh/uv/) | any recent |
| A Cookidoo account | — |
| A Telegram Bot token | from [@BotFather](https://t.me/BotFather) |
| A Google AI Studio API key | [aistudio.google.com](https://aistudio.google.com/) |

---

## Installation

```bash
# 1. Clone the repository
git clone <repo-url>
cd cookidoo-bot

# 2. Create the virtual environment and install dependencies
uv sync

# 3. Edit the configuration
cp config.toml.example config.toml   # or edit config.toml directly
```

---

## Configuration

Edit `config.toml` in the project root:

```toml
[cookidoo]
# Cookidoo account credentials
username  = "you@example.com"
password  = "your-password"

# Base URL of the Cookidoo site for your account.
# The locale (e.g. es-ES) and TTS display format are derived automatically
# from the domain. Change this if your account is on a different market.
# Examples: https://cookidoo.de  https://cookidoo.co.uk  https://cookidoo.fr
cookidoo-site = "https://cookidoo.es"

[telegram]
# Token obtained from @BotFather
token    = "123456:ABC-..."
# Telegram user ID of the only user allowed to interact with the bot
admin-id = 123456789

[google]
# API key from Google AI Studio
token          = "AIza..."
# Gemini model name
model          = "gemini-3.1-flash-lite-preview"
# Thinking budget: LOW | MEDIUM | HIGH
thinking-level = "HIGH"
```

> **`cookidoo-site`** is the base URL of the Cookidoo web frontend for your
> account's market. The locale code (e.g. `es-ES`) and Thermomix step display
> strings (e.g. `10 s/vel 10` for Spanish, `10 s/St. 10` for German) are
> derived automatically from the language set in the telegram bot.

---

## Running the bot

```bash
# Activate the virtual environment (if not already active)
source .venv/bin/activate

# Start the bot
cookidoo-bot
```

Or without activating:

```bash
uv run cookidoo-bot
```

---

## Bot commands

| Command | Description |
|---------|-------------|
| `/create` | Start the recipe adaptation workflow |
| `/cancel` | Abort the current conversation at any point |
| `/language <code>` | Change the bot UI language (e.g. `/language es`) |

### `/create` workflow

1. Send the Cookidoo recipe URL  
   (e.g. `https://cookidoo.es/recipes/recipe/es-ES/r12345`)
2. Choose whether to adapt the number of servings (Yes / No)
   - If **Yes**: send the target number of servings
3. Choose whether to translate the recipe (Yes / No)
   - Translation target is the language you set with `/language` — no extra
     prompt needed
4. The bot clones the recipe into your Cookidoo account, calls Gemini to adapt
   and/or translate it, and applies all changes via PATCH requests
5. You receive a direct link to the new custom recipe in your account

---

## Language selection

Use the `/language` command to set the bot's UI language **and** the target
translation language in one step:

```
/language es   → Spanish UI, translate recipes to Spanish
/language en   → English UI, translate recipes to English
/language de   → German UI, translate recipes to German
```

Supported codes out of the box: `en`, `es`, `fr`, `de`, `it`, `pt`, `nl`.  
The selected language also controls Thermomix TTS display strings
(e.g. `10 s/vel 10` for Spanish, `10 s/St. 10` for German, `10 s/vit. 10`
for French). The preference is saved between bot restarts.

---

## Recipe annotations

When adapting a recipe, Gemini produces fully structured steps with three
types of Cookidoo annotations:

### TTS — Thermomix machine operations

Taken 1:1 from the original recipe. These are preserved verbatim regardless
of translation or serving size changes. Display format is derived from the
`/language` setting:

| Language | Example |
|----------|---------|
| es / pt / it | `10 s/vel 10` |
| de | `10 s/St. 10` |
| fr | `10 s/vit. 10` |
| nl | `10 s/stand 10` |
| en | `10 s/speed 10` |

### INGREDIENT — ingredient links

Each ingredient explicitly used in a step is linked to the full ingredient
description. Gemini can use a **short natural alias** in the step text
(e.g. *"la carne"* instead of the full *"250 g de cabeza de lomo de cerdo,
deshuesada, cortada en trozos (3 cm)"*). The alias must appear verbatim in
the step text; the full description is stored in the annotation data.

### MODE — Thermomix cooking modes

Gemini selects and parameterises appropriate Thermomix mode activations.
Each mode's trigger keyword must appear verbatim in the step text.

| Mode | API name | Required fields |
|------|----------|-----------------|
| Dorar / Browning | `browning` | temperature (°C), time (s), power (`Intense`\|`Gentle`) |
| Amasar / Knead | `dough` | time (s) |
| Turbo | `turbo` | time (s), pulseCount |
| Al vapor / Varoma | `steaming` | speed, direction (`CW`\|`CCW`), time (s), accessory |
| Triturar / Blend | `blend` | speed, time (s) |
| Calentar / Warm-up | `warm_up` | speed, temperature (°C) |
| Cocción de arroz | `rice_cooker` | *(no extra params)* |
| Manual (TTS ops) | `manual` | speed, direction (`CW`\|`CCW`), time (s), temperature (°C, optional) |

**Steaming accessories:** `SimmeringBasket`, `Varoma`, `VaromaAndSimmeringBasket`

---

## Adding a new language

The bot's UI strings live in `languages/<code>.toml` where `<code>` is a
lowercase ISO 639-1 language code (e.g. `fr`, `de`, `pt`).

1. **Copy the English template:**

   ```bash
   cp languages/en.toml languages/fr.toml
   ```

2. **Translate every value** (the keys must stay unchanged):

   ```toml
   # languages/fr.toml
   not_authorised = "Désolé, vous n'êtes pas autorisé à utiliser ce bot."
   ask_url        = "Veuillez m'envoyer l'URL de la recette Cookidoo."
   # … etc.
   ```

   Values support Python `str.format()` placeholders such as `{recipe_id}`,
   `{available}`, `{error}` — keep them exactly as they appear in `en.toml`.

   Three additional keys control the localised Yes/No keyboard buttons and
   the language name shown in the translation prompt:

   ```toml
   yes_label     = "Oui"       # label for the Yes button
   no_label      = "Non"       # label for the No button
   language_name = "Français"  # native name shown in the translate prompt
   ```

3. **Test it** by starting the bot and sending `/language fr`.

No code changes or restarts are needed; the new file is picked up automatically.

To add TTS speed-word support for a new language, add an entry to `_SPEED_WORD`
in `src/cookidoo_bot/ai_service.py`:

```python
_SPEED_WORD: dict[str, str] = {
    "es": "vel",
    "fr": "vit.",
    # add your code here, e.g.:
    "ca": "vel",
}
```