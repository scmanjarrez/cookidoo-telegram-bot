# cookidoo-bot

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
model          = "gemini-2.5-flash"
# Thinking budget: LOW | MEDIUM | HIGH
thinking-level = "LOW"
```

> **`cookidoo-site`** is the base URL of the Cookidoo web frontend for your
> account's market. The locale code (e.g. `es-ES`) and Thermomix step display
> strings (e.g. `10 s/vel 10` for Spanish, `10 s/St. 10` for German) are
> derived automatically from the domain — no extra config needed.

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
   - If **Yes**: type the target language in plain English (e.g. `Spanish`, `French`)
4. The bot clones the recipe into your Cookidoo account, calls Gemini to adapt
   and/or translate it, and applies all changes via PATCH requests
5. You receive a direct link to the new custom recipe in your account

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

3. **Test it** by starting the bot and sending `/language fr`.

No code changes or restarts are needed; the new file is picked up automatically.