"""LiteLLM como roteador: um modelo fixo por provedor, fallback só se o anterior falhar."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.config import ConfigError, Settings, expose_provider_errors

log = logging.getLogger("uvicorn.error")

PROVIDER_LABELS = {
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "cloudflare": "Cloudflare",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "fake": "Falso",
}

FREE_ENTRY = "narrador-gratis"
PAID_ENTRY = "narrador-pago"


@dataclass
class RouterSpec:
    model_list: list[dict]
    fallbacks: list[dict]
    free_entry: str | None
    paid_entry: str | None
    secrets: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()


@dataclass
class Piece:
    text: str = ""
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class NarratorUnavailable(Exception):
    def __init__(
        self,
        message: str,
        *,
        public: bool = False,
        provider: str = "",
        model: str = "",
        reason: str = "",
    ):
        super().__init__(message)
        self.message = message
        self.public = public
        self.provider = provider
        self.model = model
        self.reason = reason


def provider_label(model: str) -> str:
    key = provider_of(model)
    return PROVIDER_LABELS.get(key, key or "Narrador")


def classify_provider_error(exc: BaseException, label: str) -> str:
    """Motivo curto para o jogador. Não inclui chave nem corpo do pedido."""
    text = f"{type(exc).__name__} {exc}".lower()
    if any(token in text for token in ("api key", "api_key", "invalid key", "unauthenticated", "permission denied", "401", "403")):
        return f"{label}: chave inválida"
    if any(token in text for token in ("not found", "404", "model_not_found", "unknown model", "is not supported", "invalid model")):
        return f"{label}: modelo não encontrado"
    if any(token in text for token in ("429", "rate limit", "ratelimit", "quota", "resource exhausted", "too many requests")):
        return f"{label}: limite atingido"
    if any(token in text for token in ("timeout", "timed out", "primeiro token", "stream vazio")):
        return f"{label}: tempo esgotado"
    return f"{label}: {type(exc).__name__}"


def player_failure_text(exc: NarratorUnavailable, settings: Settings) -> str:
    if exc.public:
        return exc.message
    base = "Os narradores não responderam agora. Sua história está salva. Tente de novo em instantes."
    if expose_provider_errors(settings) and exc.reason:
        return f"{base} {exc.reason}"
    return base


def log_narrator_failure(exc: NarratorUnavailable, secrets: tuple[str, ...]) -> None:
    cause = exc.__cause__ or exc
    detail = redact(str(cause), secrets)
    log.error(
        "narrador falhou provedor=%s modelo=%s tipo=%s detalhe=%s",
        exc.provider or "?",
        exc.model or "?",
        type(cause).__name__,
        detail,
    )


def log_startup(settings: Settings) -> None:
    if settings.fake:
        log.warning("RPG_LLM_FAKE=1: narrador falso, sem chamada remota.")
        return
    configured: list[str] = []
    catalog = (
        (
            "Gemini",
            bool(settings.gemini_api_key),
            f"{settings.gemini_model}; reserva {settings.gemini_fallback_model} (mesma chave)",
        ),
        ("OpenRouter", bool(settings.openrouter_api_key), settings.openrouter_model),
        (
            "Cloudflare",
            bool(settings.cloudflare_api_key and settings.cloudflare_account_id),
            settings.cloudflare_model,
        ),
    )
    for name, ready, model in catalog:
        if ready:
            log.info("Provedor configurado: %s modelo %s", name, model)
            configured.append(name)
        else:
            log.info("Provedor sem chave: %s (modelo previsto %s)", name, model)
    if settings.paid_api_key:
        log.info("Rota paga configurada: modelo %s", settings.paid_model)
    else:
        log.info("Rota paga sem chave (LLM_PAID_API_KEY).")
    if not configured:
        log.warning(
            "Nenhuma chave do pool grátis. Os turnos vão falhar até você definir GEMINI_API_KEY ou RPG_LLM_FAKE=1."
        )


def provider_of(model: str) -> str:
    return model.split("/", 1)[0].lower()


def normalize_gemini(model: str) -> str:
    model = model.strip()
    if not model.startswith("gemini/"):
        model = f"gemini/{model}"
    return model


def normalize_openrouter(model: str) -> str:
    bare = model.strip()
    if bare.startswith("openrouter/"):
        bare = bare[len("openrouter/") :]
    if bare == "free" or bare.endswith("/free"):
        raise ConfigError(
            "Não use o roteador openrouter/free: ele troca de modelo a cada pedido. "
            "Escolha um id fixo terminado em :free."
        )
    if not bare.endswith(":free"):
        raise ConfigError(
            "O modelo do OpenRouter no pool grátis precisa ser um id fixo terminado em :free."
        )
    return f"openrouter/{bare}"


def normalize_cloudflare(model: str) -> str:
    model = model.strip()
    if model.startswith("cloudflare/"):
        return model
    return f"cloudflare/{model}"


def build_spec(settings: Settings) -> RouterSpec:
    deployments: list[tuple[str, dict]] = []
    if settings.gemini_api_key:
        model = normalize_gemini(settings.gemini_model)
        deployments.append(
            (
                "gemini",
                {
                    "model_name": "narrador-gemini",
                    "litellm_params": {"model": model, "api_key": settings.gemini_api_key},
                },
            )
        )
        fallback = normalize_gemini(settings.gemini_fallback_model)
        if fallback != model:
            deployments.append(
                (
                    "gemini",
                    {
                        "model_name": "narrador-gemini-reserva",
                        "litellm_params": {"model": fallback, "api_key": settings.gemini_api_key},
                    },
                )
            )
    if settings.openrouter_api_key:
        model = normalize_openrouter(settings.openrouter_model)
        deployments.append(
            (
                "openrouter",
                {
                    "model_name": "narrador-openrouter",
                    "litellm_params": {
                        "model": model,
                        "api_key": settings.openrouter_api_key,
                    },
                },
            )
        )
    if settings.cloudflare_api_key or settings.cloudflare_account_id:
        if not settings.cloudflare_api_key or not settings.cloudflare_account_id:
            raise ConfigError("Cloudflare precisa de CLOUDFLARE_API_TOKEN e CLOUDFLARE_ACCOUNT_ID juntos.")
        model = normalize_cloudflare(settings.cloudflare_model)
        account = settings.cloudflare_account_id
        deployments.append(
            (
                "cloudflare",
                {
                    "model_name": "narrador-cloudflare",
                    "litellm_params": {
                        "model": model,
                        "api_key": settings.cloudflare_api_key,
                        "api_base": f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
                    },
                },
            )
        )

    paid_params: dict | None = None
    if settings.paid_api_key:
        if "/" not in settings.paid_model:
            raise ConfigError(
                "LLM_PAID_MODEL precisa incluir o provedor, por exemplo groq/openai/gpt-oss-20b ou deepseek/deepseek-chat."
            )
        paid_provider = provider_of(settings.paid_model)
        for name, item in deployments:
            if name == paid_provider and item["litellm_params"].get("api_key") != settings.paid_api_key:
                raise ConfigError(
                    f"A rota paga usa outra chave de {paid_provider}. "
                    "Uma conta por provedor; não rotacione contas do mesmo provedor."
                )
        paid_params = {"model": settings.paid_model, "api_key": settings.paid_api_key}
        if settings.paid_api_base:
            paid_params["api_base"] = settings.paid_api_base

    model_list: list[dict] = []
    providers: list[str] = []
    fallback_names: list[str] = []
    free_entry: str | None = None
    for index, (name, item) in enumerate(deployments):
        logical = FREE_ENTRY if index == 0 else item["model_name"]
        if index == 0:
            free_entry = logical
        else:
            fallback_names.append(logical)
        params = dict(item["litellm_params"])
        model_list.append({"model_name": logical, "litellm_params": params})
        if name not in providers:
            providers.append(name)

    # Uma implantação por nome lógico: o LiteLLM não embaralha várias contas.
    names = [item["model_name"] for item in model_list]
    if len(names) != len(set(names)):
        raise ConfigError("Cada provedor do pool grátis entra uma única vez.")

    fallbacks = [{free_entry: fallback_names}] if free_entry and fallback_names else []
    paid_entry = None
    if paid_params is not None:
        model_list.append({"model_name": PAID_ENTRY, "litellm_params": paid_params})
        paid_entry = PAID_ENTRY
    return RouterSpec(
        model_list=model_list,
        fallbacks=fallbacks,
        free_entry=free_entry,
        paid_entry=paid_entry,
        secrets=settings.secrets,
        providers=tuple(providers),
    )


def redact(text: str, secrets: tuple[str, ...]) -> str:
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 6:
            cleaned = cleaned.replace(secret, "••••")
    return cleaned


def chunk_text(chunk: object) -> str:
    choices = getattr(chunk, "choices", None)
    if choices is None and isinstance(chunk, dict):
        choices = chunk.get("choices")
    if not choices:
        return ""
    first = choices[0]
    delta = first.get("delta") if isinstance(first, dict) else getattr(first, "delta", None)
    if delta is None:
        return ""
    content = delta.get("content") if isinstance(delta, dict) else getattr(delta, "content", None)
    return content or ""


def chunk_model(chunk: object) -> str:
    model = getattr(chunk, "model", None)
    if model is None and isinstance(chunk, dict):
        model = chunk.get("model")
    return str(model or "")


def chunk_usage(chunk: object) -> tuple[int | None, int | None]:
    usage = getattr(chunk, "usage", None)
    if usage is None and isinstance(chunk, dict):
        usage = chunk.get("usage")
    if not usage:
        return None, None
    prompt = usage.get("prompt_tokens") if isinstance(usage, dict) else getattr(usage, "prompt_tokens", None)
    completion = (
        usage.get("completion_tokens") if isinstance(usage, dict) else getattr(usage, "completion_tokens", None)
    )
    return (
        int(prompt) if isinstance(prompt, int) else None,
        int(completion) if isinstance(completion, int) else None,
    )


class FakeGateway:
    """Narrador falso para testes e para o script de carga. Não chama a rede."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, str]]]] = []

    async def stream(self, route: str, messages: list[dict[str, str]]):
        self.calls.append((route, messages))
        text = (
            "<narrativa>\nA névoa se move e a cena espera a sua próxima ação.\n</narrativa>\n"
            '<estado>\n{"beat":"A névoa se moveu.","quando":"depois"}\n</estado>'
        )
        yield Piece(text=text, model=f"fake-{route}")


class UnconfiguredGateway:
    async def stream(self, route: str, messages: list[dict[str, str]]):
        if False:
            yield Piece()
        raise NarratorUnavailable(
            "O pool de narradores não está configurado. Defina as chaves no ambiente "
            "(Gemini, OpenRouter ou Cloudflare) ou RPG_LLM_FAKE=1 para o modo de teste.",
            public=True,
        )


@dataclass(frozen=True)
class Attempt:
    label: str
    model: str
    api_key: str
    api_base: str = ""


def attempts_for(settings: Settings, route: str) -> list[Attempt]:
    """Ordem de tentativa. Os dois ids do Gemini usam a mesma chave."""
    if route == "paid":
        if not settings.paid_api_key:
            return []
        return [
            Attempt(
                provider_label(settings.paid_model),
                settings.paid_model,
                settings.paid_api_key,
                settings.paid_api_base,
            )
        ]
    attempts: list[Attempt] = []
    if settings.gemini_api_key:
        primary = normalize_gemini(settings.gemini_model)
        attempts.append(Attempt("Gemini", primary, settings.gemini_api_key))
        fallback = normalize_gemini(settings.gemini_fallback_model)
        if fallback != primary:
            attempts.append(Attempt("Gemini", fallback, settings.gemini_api_key))
    if settings.openrouter_api_key:
        attempts.append(
            Attempt("OpenRouter", normalize_openrouter(settings.openrouter_model), settings.openrouter_api_key)
        )
    if settings.cloudflare_api_key and settings.cloudflare_account_id:
        model = normalize_cloudflare(settings.cloudflare_model)
        base = f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1"
        attempts.append(Attempt("Cloudflare", model, settings.cloudflare_api_key, base))
    return attempts


def message_text(response: object) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = getattr(message, "content", None)
    return content or ""


class LiteLLMGateway:
    def __init__(self, spec: RouterSpec, settings: Settings, complete=None):
        self.spec = spec
        self.settings = settings
        self.complete = complete or _litellm_complete

    async def stream(self, route: str, messages: list[dict[str, str]]):
        attempts = attempts_for(self.settings, route)
        if not attempts:
            if route == "paid":
                raise NarratorUnavailable(
                    "A rota paga não está configurada. Defina LLM_PAID_MODEL e LLM_PAID_API_KEY.",
                    public=True,
                )
            raise NarratorUnavailable(
                "Nenhum provedor do pool grátis está configurado. "
                "Defina a chave do Gemini, do OpenRouter ou do Cloudflare.",
                public=True,
            )
        last: NarratorUnavailable | None = None
        sent = False
        for attempt in attempts:
            log.info("Narrando rota=%s provedor=%s modelo=%s", route, attempt.label, attempt.model)
            try:
                async for piece in self._one(attempt, messages):
                    if piece.text:
                        sent = True
                    yield piece
                return
            except Exception as exc:
                last = self._failure(exc, attempt.label, attempt.model)
                if sent:
                    raise last from exc
                log.warning(
                    "narrador segue para o próximo modelo=%s motivo=%s",
                    attempt.model,
                    last.reason,
                )
        assert last is not None
        raise last

    async def _one(self, attempt: Attempt, messages: list[dict[str, str]]):
        produced = False
        try:
            async for piece in self._stream_attempt(attempt, messages):
                if piece.text:
                    produced = True
                yield piece
            if produced:
                return
            raise TimeoutError("stream vazio")
        except Exception as exc:
            if produced:
                raise
            log.warning(
                "stream sem texto modelo=%s tipo=%s; tentando sem streaming",
                attempt.model,
                type(exc).__name__,
            )
        response = await self._call(attempt, messages, stream=False)
        text = message_text(response)
        if not text.strip():
            raise TimeoutError("resposta vazia")
        yield Piece(text=text, model=attempt.model or chunk_model(response))

    async def _stream_attempt(self, attempt: Attempt, messages: list[dict[str, str]]):
        response = await self._call(attempt, messages, stream=True)
        iterator = response.__aiter__()
        deadline = time.monotonic() + self.settings.first_token_seconds
        got_text = False
        try:
            while not got_text:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("primeiro token")
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), remaining)
                except StopAsyncIteration as exc:
                    raise TimeoutError("stream vazio") from exc
                piece = _piece_from_chunk(chunk)
                if piece.text:
                    got_text = True
                    yield piece
                elif piece.prompt_tokens is not None:
                    yield piece
            end = time.monotonic() + self.settings.llm_timeout
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), remaining)
                except StopAsyncIteration:
                    return
                piece = _piece_from_chunk(chunk)
                if piece.text or piece.prompt_tokens is not None:
                    yield piece
        finally:
            aclose = getattr(iterator, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass

    async def _call(
        self,
        attempt: Attempt,
        messages: list[dict[str, str]],
        *,
        stream: bool,
        max_tokens: int | None = None,
    ):
        timeout = self.settings.first_token_seconds if stream else self.settings.llm_timeout
        kwargs: dict = {
            "model": attempt.model,
            "messages": messages,
            "api_key": attempt.api_key,
            "stream": stream,
            "timeout": timeout,
            "stream_timeout": self.settings.first_token_seconds,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens if max_tokens is None else max_tokens,
            "drop_params": True,
        }
        if attempt.model.startswith("gemini/"):
            kwargs["reasoning_effort"] = "minimal"
        if attempt.api_base:
            kwargs["api_base"] = attempt.api_base
        return await self.complete(**kwargs)

    def _failure(self, exc: Exception, label: str, model_id: str) -> NarratorUnavailable:
        reason = classify_provider_error(exc, label)
        return NarratorUnavailable(
            redact(str(exc), self.spec.secrets),
            provider=label,
            model=model_id,
            reason=reason,
        )


def _piece_from_chunk(chunk: object) -> Piece:
    prompt_tokens, completion_tokens = chunk_usage(chunk)
    return Piece(
        text=chunk_text(chunk),
        model=chunk_model(chunk),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


async def _litellm_complete(**kwargs):
    import os

    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm

    litellm.telemetry = False
    litellm.drop_params = True
    return await litellm.acompletion(**kwargs)


def build_gateway(settings: Settings):
    if settings.fake:
        return FakeGateway()
    spec = build_spec(settings)
    if not spec.model_list:
        return UnconfiguredGateway()
    return LiteLLMGateway(spec, settings)
