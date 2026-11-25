"""Configuração por ambiente. Chaves só existem em variáveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """Carrega um .env local sem sobrescrever variáveis já exportadas."""
    file = Path(path)
    if not file.is_file():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class ConfigError(ValueError):
    """Configuração inválida. A mensagem é segura para mostrar no log de subida."""


def one_secret(name: str, value: str) -> str:
    """Uma conta por provedor. Várias chaves no mesmo campo são recusadas."""
    parts = [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
    if len(parts) > 1:
        raise ConfigError(
            f"{name} tem mais de uma chave. Use uma conta por provedor; "
            "rotacionar várias contas do mesmo provedor viola os termos de uso."
        )
    return parts[0] if parts else ""


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _int(name: str, value: str, default: int) -> int:
    raw = value.strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} precisa ser um inteiro.") from exc


@dataclass(frozen=True)
class Settings:
    database_path: str = "data/rpg.sqlite"
    fake: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini/gemini-2.5-flash-lite"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemma-4-26b-a4b-it:free"
    cloudflare_api_key: str = ""
    cloudflare_account_id: str = ""
    cloudflare_model: str = "@cf/meta/llama-3.1-8b-instruct-fast"
    paid_api_key: str = ""
    paid_model: str = "groq/openai/gpt-oss-20b"
    paid_api_base: str = ""
    free_turns_per_day: int = 20
    trial_turns_per_day: int = 40
    paid_turns_per_day: int = 0
    trial_days: int = 7
    day_offset_hours: int = -3
    max_concurrent: int = 20
    max_waiting: int = 80
    queue_wait_seconds: float = 8
    max_recent: int = 8
    max_context_tokens: int = 2800
    summary_max_tokens: int = 450
    message_max_tokens: int = 180
    temperature: float = 0.8
    max_output_tokens: int = 700
    llm_timeout: float = 40
    moderation: str = "basic"
    moderation_webhook: str = ""
    moderation_terms: tuple[str, ...] = ()
    billing_checkout_url: str = ""
    allow_dev_plan_toggle: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(
            secret
            for secret in (
                self.gemini_api_key,
                self.openrouter_api_key,
                self.cloudflare_api_key,
                self.cloudflare_account_id,
                self.paid_api_key,
            )
            if secret
        )


def load_settings(env: dict[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env

    def get(name: str, default: str = "") -> str:
        return source.get(name, default) or ""

    moderation = get("MODERATION", "basic").strip().lower() or "basic"
    if moderation not in {"off", "basic", "webhook"}:
        raise ConfigError("MODERATION deve ser off, basic ou webhook.")
    terms = tuple(part.strip() for part in get("MODERATION_TERMS").split(",") if part.strip())
    return Settings(
        database_path=get("DATABASE_PATH", "data/rpg.sqlite"),
        fake=_bool(get("RPG_LLM_FAKE")),
        gemini_api_key=one_secret("GEMINI_API_KEY", get("GEMINI_API_KEY")),
        gemini_model=get("LLM_GEMINI_MODEL", "gemini/gemini-2.5-flash-lite").strip()
        or "gemini/gemini-2.5-flash-lite",
        openrouter_api_key=one_secret("OPENROUTER_API_KEY", get("OPENROUTER_API_KEY")),
        openrouter_model=get("LLM_OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free").strip()
        or "google/gemma-4-26b-a4b-it:free",
        cloudflare_api_key=one_secret("CLOUDFLARE_API_TOKEN", get("CLOUDFLARE_API_TOKEN")),
        cloudflare_account_id=one_secret("CLOUDFLARE_ACCOUNT_ID", get("CLOUDFLARE_ACCOUNT_ID")),
        cloudflare_model=get("LLM_CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct-fast").strip()
        or "@cf/meta/llama-3.1-8b-instruct-fast",
        paid_api_key=one_secret("LLM_PAID_API_KEY", get("LLM_PAID_API_KEY")),
        paid_model=get("LLM_PAID_MODEL", "groq/openai/gpt-oss-20b").strip() or "groq/openai/gpt-oss-20b",
        paid_api_base=get("LLM_PAID_API_BASE").strip(),
        free_turns_per_day=_int("FREE_TURNS_PER_DAY", get("FREE_TURNS_PER_DAY"), 20),
        trial_turns_per_day=_int("TRIAL_TURNS_PER_DAY", get("TRIAL_TURNS_PER_DAY"), 40),
        paid_turns_per_day=_int("PAID_TURNS_PER_DAY", get("PAID_TURNS_PER_DAY"), 0),
        trial_days=_int("TRIAL_DAYS", get("TRIAL_DAYS"), 7),
        day_offset_hours=_int("PLAYER_UTC_OFFSET_HOURS", get("PLAYER_UTC_OFFSET_HOURS"), -3),
        max_concurrent=_int("LLM_MAX_CONCURRENCY", get("LLM_MAX_CONCURRENCY"), 20),
        max_waiting=_int("LLM_MAX_WAITING", get("LLM_MAX_WAITING"), 80),
        queue_wait_seconds=float(get("LLM_QUEUE_WAIT_SECONDS", "8") or "8"),
        max_recent=_int("NARRATOR_MAX_RECENT", get("NARRATOR_MAX_RECENT"), 8),
        max_context_tokens=_int("NARRATOR_MAX_TOKENS", get("NARRATOR_MAX_TOKENS"), 2800),
        summary_max_tokens=_int("SUMMARY_MAX_TOKENS", get("SUMMARY_MAX_TOKENS"), 450),
        message_max_tokens=_int("MESSAGE_MAX_TOKENS", get("MESSAGE_MAX_TOKENS"), 180),
        temperature=float(get("NARRATOR_TEMPERATURE", "0.8") or "0.8"),
        max_output_tokens=_int("NARRATOR_MAX_OUTPUT_TOKENS", get("NARRATOR_MAX_OUTPUT_TOKENS"), 700),
        llm_timeout=float(get("LLM_TIMEOUT_SECONDS", "40") or "40"),
        moderation=moderation,
        moderation_webhook=get("MODERATION_WEBHOOK_URL").strip(),
        moderation_terms=terms,
        billing_checkout_url=get("BILLING_CHECKOUT_URL").strip(),
        allow_dev_plan_toggle=_bool(get("ALLOW_DEV_PLAN_TOGGLE")),
        host=get("HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int("PORT", get("PORT"), 8000),
    )
