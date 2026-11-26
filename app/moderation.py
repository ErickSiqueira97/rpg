"""Hook simples de moderação na entrada e na saída."""

from __future__ import annotations

import re
import unicodedata

import httpx

_MINOR = re.compile(
    r"\b(crianca|criancas|infantil|menor de idade|menores de idade|pre-adolescente|"
    r"child|children|underage|loli|shota)\b",
    re.IGNORECASE,
)
_SEXUAL = re.compile(
    r"\b(sexo|sexual|pornografia|porn|nudez|estupro|rape|nsfw|erotico|erotica)\b",
    re.IGNORECASE,
)
_ALONE = re.compile(r"\b(pedofil\w*|child porn|pornografia infantil|csam)\b", re.IGNORECASE)

REFUSAL = "Essa ação não entra na crônica."


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    without = "".join(char for char in normalized if not unicodedata.combining(char))
    return without.lower()


def basic_block(text: str, extra_terms: tuple[str, ...] = ()) -> bool:
    folded = fold(text)
    if _ALONE.search(folded):
        return True
    if _MINOR.search(folded) and _SEXUAL.search(folded):
        return True
    return any(fold(term) and fold(term) in folded for term in extra_terms)


class Moderator:
    def __init__(self, mode: str, extra_terms: tuple[str, ...] = (), webhook_url: str = ""):
        self.mode = mode
        self.extra_terms = extra_terms
        self.webhook_url = webhook_url

    async def check(self, text: str, direction: str) -> str | None:
        if self.mode == "off":
            return None
        if basic_block(text, self.extra_terms):
            return REFUSAL
        if self.mode == "webhook" and self.webhook_url:
            allowed = await self._webhook(text, direction)
            if allowed is False:
                return REFUSAL
        return None

    async def _webhook(self, text: str, direction: str) -> bool | None:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.post(
                    self.webhook_url,
                    json={"text": text, "direction": direction},
                )
            if response.status_code >= 400:
                return None
            payload = response.json()
            if isinstance(payload, dict) and "allowed" in payload:
                return bool(payload["allowed"])
        except (httpx.HTTPError, ValueError):
            return None
        return None
