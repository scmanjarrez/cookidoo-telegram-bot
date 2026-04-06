"""Async wrapper around the Cookidoo web frontend API (cookie-based auth)."""

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import aiohttp
from bs4 import BeautifulSoup, Comment, NavigableString, Tag


def iso8601_to_seconds(s: str) -> int:
    """Convert an ISO 8601 duration string (e.g. 'PT1H30M') to seconds."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s or "")
    if not m:
        return 0
    return int(
        int(m.group(1) or 0) * 3600
        + int(m.group(2) or 0) * 60
        + float(m.group(3) or 0)
    )


# ─── Original step structure parsed from the edit-page HTML ───


@dataclass
class OriginalTTS:
    """Original TTS machine operation parsed from a Cookidoo edit-page step."""

    display_text: str  # inner text of <cr-tts>, e.g. "10 s/obr. 10"
    speed: str  # e.g. "10"
    time: int  # e.g. 10
    time_unit: str  # "s" or "min"
    temperature: dict | None  # {"value": "80", "unit": "C"} or None


@dataclass
class OriginalStep:
    """A single recipe step with its list of TTS annotations."""

    text: str  # full step text (TTS display included)
    tts_list: list[OriginalTTS] = dc_field(default_factory=list)


# ─── Recipe section structure ──────────────────────────────────────────────


@dataclass
class RecipeSection:
    """One named section of ingredients or steps in a Cookidoo recipe."""

    name: str | None  # None = unnamed / first section
    item_count: int  # number of list items belonging to this section


@dataclass
class RecipeSections:
    """Ingredient and step section metadata parsed from a recipe page."""

    ingredient_sections: list[RecipeSection]
    step_sections: list[RecipeSection]
    # One entry per ingredient <li> across ALL inner sections, in document
    # order.  None means the ingredient has no alternative.
    ingredient_alternatives: list[str | None] = dc_field(default_factory=list)
    # Existing tips/hints text from the recipe page; None when absent.
    original_hints: str | None = None


# ─── HTML parsing ───────────────────────────────────────────────────────────


def _attr(tag: Tag, name: str) -> str | None:
    """Return a single-string attribute from a BS4 Tag, or None."""
    val = tag.get(name)
    if val is None:
        return None
    return val if isinstance(val, str) else val[0]


def _parse_tts_tag(tag: Tag) -> OriginalTTS:
    """Build an OriginalTTS from a <cr-tts> BS4 Tag."""
    temp_val = _attr(tag, "temperature")
    return OriginalTTS(
        display_text=tag.get_text(strip=True),
        speed=_attr(tag, "speed") or "",
        time=int(_attr(tag, "time") or 0),
        time_unit=_attr(tag, "time-unit") or "s",
        temperature=(
            {
                "value": temp_val,
                "unit": _attr(tag, "temperature-unit") or "C",
            }
            if temp_val
            else None
        ),
    )


def _parse_tips_section(tips_outer: Tag) -> str | None:
    r"""Extract hints text from a tips-section Tag.

    Handles two real-world structures:
    - Original recipe URL: ``<rdp-tips>`` wrapping ``<ul>/<li>`` items
      (one tip per ``<li>``).
    - Created-recipe view: ``<div>`` wrapping a single
      ``<p style="white-space: pre-wrap">`` with tips separated by ``\n\n``.
    """
    li_items = [
        t
        for t in tips_outer.find_all("li")
        if isinstance(t, Tag) and t.get_text(strip=True)
    ]
    if li_items:
        parts: list[str] = [
            re.sub(r"\s+", " ", t.get_text(" ", strip=True)) for t in li_items
        ]
    else:
        parts = []
        for p_tag in tips_outer.find_all("p"):
            if not isinstance(p_tag, Tag):
                continue
            raw = p_tag.get_text(strip=True)
            if not raw:
                continue
            for raw_chunk in re.split(r"(?:\r?\n){2,}", raw):
                norm = re.sub(r"[ \t]+", " ", raw_chunk.strip())
                if norm:
                    parts.append(norm)
    return "\n\n".join(parts) if parts else None


def _parse_recipe_sections(html: str) -> RecipeSections:
    """Parse ingredient/step sections and alternatives from a recipe page."""
    soup = BeautifulSoup(html, "html.parser")

    def _inner_sections(outer: Tag) -> list[RecipeSection]:
        result: list[RecipeSection] = []
        for inner in outer.find_all(class_="recipe-content__inner-section"):
            if not isinstance(inner, Tag):
                continue
            heading = inner.find(["h1", "h2", "h3", "h4", "h5", "h6"])
            name = (
                heading.get_text(strip=True)
                if isinstance(heading, Tag)
                else None
            ) or None
            result.append(
                RecipeSection(
                    name=name,
                    item_count=len(inner.find_all("li")),
                )
            )
        return result

    # Ingredients outer: real pages use id="ingredients-section"; the
    # class fallback covers unit-test HTML.
    ingr_raw = soup.find(id="ingredients-section") or soup.find(
        class_="ingredients-section"
    )
    ingr_outer: Tag | None = ingr_raw if isinstance(ingr_raw, Tag) else None

    # Preparation/steps outer: real pages use id="preparation-steps-section";
    # class fallback covers unit-test HTML.
    prep_raw = soup.find(id="preparation-steps-section") or soup.find(
        class_="preparation-steps-section"
    )
    prep_outer: Tag | None = prep_raw if isinstance(prep_raw, Tag) else None

    # Collect ingredient alternatives in document order — one entry per
    # <li> inside the ingredient section, None when absent.
    ingr_alts: list[str | None] = []
    if ingr_outer is not None:
        for li in ingr_outer.find_all("li"):
            if not isinstance(li, Tag):
                continue
            alt = li.find(class_="recipe-ingredient__alternative")
            ingr_alts.append(
                re.sub(r"\s+", " ", alt.get_text(" ", strip=True)) or None
                if isinstance(alt, Tag)
                else None
            )

    # Parse tips/hints: both real-page structures use id="tips-section".
    tips_raw = soup.find(id="tips-section")
    tips_outer: Tag | None = tips_raw if isinstance(tips_raw, Tag) else None
    original_hints = (
        _parse_tips_section(tips_outer) if tips_outer is not None else None
    )

    return RecipeSections(
        ingredient_sections=(
            _inner_sections(ingr_outer) if ingr_outer is not None else []
        ),
        step_sections=(
            _inner_sections(prep_outer) if prep_outer is not None else []
        ),
        ingredient_alternatives=ingr_alts,
        original_hints=original_hints,
    )


def _collect_step_text(
    text_field: Tag,
) -> tuple[list[str], list[OriginalTTS]]:
    """Walk a cr-text-field Tag and collect plain text and TTS entries."""
    text_parts: list[str] = []
    tts_list: list[OriginalTTS] = []
    for node in text_field.descendants:
        if isinstance(node, Tag) and node.name == "cr-tts":
            tts_list.append(_parse_tts_tag(node))
        elif isinstance(node, NavigableString) and not isinstance(
            node, Comment
        ):
            text_parts.append(str(node))
    return text_parts, tts_list


def _parse_edit_steps(html: str) -> list[OriginalStep]:
    """Parse <cr-step-text-field> elements from a Cookidoo edit-page."""
    soup = BeautifulSoup(html, "html.parser")
    steps: list[OriginalStep] = []

    for step_field in soup.find_all("cr-step-text-field"):
        if not isinstance(step_field, Tag):
            continue
        # Content lives in the first cr-text-field NOT inside
        # cr-text-field-actions (which holds the UI action buttons).
        text_field: Tag | None = next(
            (
                tf
                for tf in step_field.find_all("cr-text-field")
                if isinstance(tf, Tag)
                and tf.find_parent("cr-text-field-actions") is None
            ),
            None,
        )
        if text_field is None:
            continue

        text_parts, tts_list = _collect_step_text(text_field)
        text = "".join(text_parts).strip()
        if text:
            steps.append(OriginalStep(text=text, tts_list=tts_list))

    return steps


_TLD_TO_LOCALE: dict[str, str] = {
    "es": "es-ES",
    "de": "de-DE",
    "fr": "fr-FR",
    "it": "it-IT",
    "pt": "pt-PT",
    "nl": "nl-NL",
    "at": "de-AT",
    "be": "nl-BE",
    "ch": "de-CH",
    "co.uk": "en-GB",
    "international": "en-GB",
    "com.au": "en-AU",
}


_HTTP_CLIENT_ERR = 400


def site_to_locale(site: str) -> str:
    """Derive the Cookidoo locale string (e.g. 'es-ES') from a site URL."""
    hostname = urlparse(site).hostname or ""
    # strip leading subdomain, e.g. 'cookidoo.es' → 'es'
    parts = hostname.split(".")
    if parts and parts[0] == "cookidoo":
        parts = parts[1:]
    tld = ".".join(parts)
    return _TLD_TO_LOCALE.get(tld, "en-GB")


class CookidooWebClient:
    """Thin async client for the Cookidoo web frontend API."""

    _AJAX_HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "application/json",
        "X-Requested-With": "xmlhttprequest",
    }

    def __init__(
        self,
        session: aiohttp.ClientSession,
        site: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize with a session, site URL, and login credentials."""
        self._session = session
        self._base = site.rstrip("/")
        self._locale = site_to_locale(site)
        self._username = username
        self._password = password

    @property
    def locale(self) -> str:
        """Return the Cookidoo locale code (e.g. 'es-ES')."""
        return self._locale

    async def login(self) -> None:
        """Authenticate via Cookidoo's OAuth2 CIAM flow."""
        market = self._locale.split("-")[0]
        async with self._session.get(
            f"{self._base}/oauth2/start",
            params={
                "market": market,
                "ui_locales": self._locale,
                "rd": f"/foundation/{self._locale}",
            },
            allow_redirects=True,
        ) as r:
            final_url = str(r.url)
            html = await r.text()

        qs = parse_qs(urlparse(final_url).query)
        request_id: str | None = next(iter(qs.get("requestId", [])), None)
        if not request_id:
            inp = BeautifulSoup(html, "html.parser").find(
                "input", {"name": "requestId"}
            )
            if isinstance(inp, Tag):
                raw = inp.get("value")
                if raw:
                    request_id = raw if isinstance(raw, str) else raw[0]
        if not request_id:
            msg = "Could not find requestId in Cookidoo OAuth2 login page"
            raise RuntimeError(msg)

        form = aiohttp.FormData()
        form.add_field("requestId", request_id)
        form.add_field("username", self._username)
        form.add_field("password", self._password)
        _ciam = "https://ciam.prod.cookidoo.vorwerk-digital.com"
        async with self._session.post(
            f"{_ciam}/login-srv/login",
            data=form,
            allow_redirects=True,
        ) as r:
            if r.status >= _HTTP_CLIENT_ERR:
                msg = f"Cookidoo login failed (HTTP {r.status})"
                raise RuntimeError(msg)

    async def add_custom_recipe(self, recipe_url: str) -> dict:
        """POST add-to-cookidoo and return the full response JSON."""
        url = f"{self._base}/created-recipes/{self._locale}/add-to-cookidoo"
        async with self._session.post(
            url,
            headers=self._AJAX_HEADERS,
            json={"recipeUrl": recipe_url, "partnerId": "cookidoo"},
        ) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def patch_recipe(self, recipe_id: str, payload: dict) -> None:
        """PATCH a single recipe payload to the Cookidoo API."""
        url = f"{self._base}/created-recipes/{self._locale}/{recipe_id}"
        async with self._session.patch(
            url, headers=self._AJAX_HEADERS, json=payload
        ) as r:
            r.raise_for_status()

    def recipe_url(self, recipe_id: str) -> str:
        """Return the Cookidoo URL for the given recipe ID."""
        return f"{self._base}/created-recipes/{self._locale}/{recipe_id}"

    async def get_original_steps(self, recipe_id: str) -> list[OriginalStep]:
        """Fetch the edit page and parse the step list with TTS annotations.

        Section structure is NOT available on the edit page and must be
        fetched separately via get_recipe_sections from the original URL.
        """
        url = (
            f"{self._base}/created-recipes/{self._locale}/{recipe_id}"
            f"/edit/ingredients-and-preparation-steps"
        )
        async with self._session.get(
            url,
            params={"active": "steps"},
            allow_redirects=True,
        ) as r:
            r.raise_for_status()
            html = await r.text()
        return _parse_edit_steps(html)

    async def get_recipe_sections(self, recipe_url: str) -> RecipeSections:
        """Fetch the original recipe page and parse its section structure."""
        async with self._session.get(recipe_url, allow_redirects=True) as r:
            r.raise_for_status()
            html = await r.text()
        return _parse_recipe_sections(html)
