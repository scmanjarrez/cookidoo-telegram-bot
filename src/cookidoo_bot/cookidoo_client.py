"""Async wrapper around the Cookidoo web frontend API (cookie-based auth)."""

import html as _html_lib
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import parse_qs, quote, urlparse

import aiohttp


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


class _StepHTMLParser(HTMLParser):
    """Parses <cr-step-text-field> elements from Cookidoo edit-page HTML."""

    def __init__(self) -> None:
        """Initialize the HTML parser state."""
        super().__init__()
        self.steps: list[OriginalStep] = []
        self._in_step = False
        self._capturing = False  # inside the main content <cr-text-field>
        self._cf_depth = 0  # nesting depth inside cr-text-field
        self._ignore_depth = 0  # depth within ignored subtrees
        self._in_tts = False
        self._tts_attrs: dict = {}
        self._text_parts: list[str] = []
        self._tts_list: list[OriginalTTS] = []

    def _flush(self) -> None:
        text = "".join(self._text_parts).strip()
        if text:
            self.steps.append(
                OriginalStep(text=text, tts_list=list(self._tts_list))
            )
        self._in_step = False
        self._capturing = False
        self._cf_depth = 0
        self._ignore_depth = 0
        self._in_tts = False
        self._tts_attrs = {}
        self._text_parts = []
        self._tts_list = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "cr-step-text-field":
            self._flush()
            self._in_step = True
            return

        if not self._in_step:
            return

        if self._ignore_depth > 0:
            self._ignore_depth += 1
            return

        if tag == "cr-text-field-actions":
            self._ignore_depth += 1
            return

        if tag == "cr-text-field":
            if not self._capturing:
                self._capturing = True
                self._cf_depth = 1
            else:
                self._cf_depth += 1
            return

        if not self._capturing:
            return

        if tag == "cr-tts":
            self._in_tts = True
            self._tts_attrs = dict(attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self._in_step:
            return

        if self._ignore_depth > 0:
            self._ignore_depth -= 1
            return

        if tag == "cr-step-text-field":
            self._flush()
            return

        if tag == "cr-text-field" and self._capturing:
            self._cf_depth -= 1
            if self._cf_depth == 0:
                self._capturing = False
            return

        if not self._capturing:
            return

        if tag == "cr-tts":
            self._in_tts = False
            self._tts_attrs = {}

    def handle_data(self, data: str) -> None:
        if not self._capturing or self._ignore_depth > 0:
            return

        if self._in_tts:
            stripped = data.strip()
            if stripped:
                temp_val = self._tts_attrs.get("temperature")
                self._tts_list.append(
                    OriginalTTS(
                        display_text=stripped,
                        speed=self._tts_attrs.get("speed", ""),
                        time=int(self._tts_attrs.get("time", 0)),
                        time_unit=self._tts_attrs.get("time-unit", "s"),
                        temperature=(
                            {
                                "value": temp_val,
                                "unit": self._tts_attrs.get(
                                    "temperature-unit", "C"
                                ),
                            }
                            if temp_val
                            else None
                        ),
                    )
                )
            self._text_parts.append(data)  # TTS text is part of the step text
        else:
            self._text_parts.append(_html_lib.unescape(data))


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
        rd = f"/foundation/{self._locale}"
        start_url = (
            f"{self._base}/oauth2/start"
            f"?market={market}&ui_locales={self._locale}"
            f"&rd={quote(rd, safe='')}"
        )
        async with self._session.get(start_url, allow_redirects=True) as r:
            final_url = str(r.url)
            html = await r.text()

        qs = parse_qs(urlparse(final_url).query)
        request_id: str | None = next(iter(qs.get("requestId", [])), None)
        if not request_id:
            m = re.search(
                r'name=["\']requestId["\'].+?value=["\']([^"\']+)',
                html,
                re.DOTALL,
            )
            if not m:
                m = re.search(
                    r'value=["\']([^"\']+)["\'].+?name=["\']requestId',
                    html,
                    re.DOTALL,
                )
            if m:
                request_id = m.group(1)
        if not request_id:
            msg = "Could not find requestId in Cookidoo OAuth2 login page"
            raise RuntimeError(msg)

        post_data = (
            f"requestId={quote(request_id, safe='')}"
            f"&username={quote(self._username, safe='')}"
            f"&password={quote(self._password, safe='')}"
        )
        _ciam = "https://ciam.prod.cookidoo.vorwerk-digital.com"
        async with self._session.post(
            f"{_ciam}/login-srv/login",
            data=post_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
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
        """Fetch the edit page and parse steps with TTS annotations."""
        url = (
            f"{self._base}/created-recipes/{self._locale}/{recipe_id}"
            f"/edit/ingredients-and-preparation-steps?active=steps"
        )
        async with self._session.get(url, allow_redirects=True) as r:
            r.raise_for_status()
            html = await r.text()
        parser = _StepHTMLParser()
        parser.feed(html)
        return parser.steps
