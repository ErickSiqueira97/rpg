from types import SimpleNamespace
import time

import logging

import pytest

from app.config import DEFAULT_GEMINI_FALLBACK, DEFAULT_GEMINI_MODEL, ConfigError, Settings, load_settings
from app.check_llm import run as check_run
from app.llm import (
    OVERLOAD_MESSAGE,
    LiteLLMGateway,
    NarratorUnavailable,
    build_spec,
    classify_provider_error,
    log_startup,
    player_failure_text,
)


def test_pool_tem_uma_conta_por_provedor_e_fallback_nessa_ordem():
    settings = Settings(
        gemini_api_key="gemini-key",
        openrouter_api_key="openrouter-key",
        openrouter_model="google/gemma-4-26b-a4b-it:free",
        cloudflare_api_key="cf-key",
        cloudflare_account_id="conta-cf",
        paid_api_key="groq-key",
        paid_model="groq/openai/gpt-oss-20b",
    )
    spec = build_spec(settings)
    assert spec.providers == ("gemini", "openrouter", "cloudflare")
    assert spec.free_entry == "narrador-gratis"
    assert spec.paid_entry == "narrador-pago"
    assert spec.fallbacks == [
        {
            "narrador-gratis": [
                "narrador-gemini-reserva-1",
                "narrador-gemini-reserva-2",
                "narrador-openrouter",
                "narrador-cloudflare",
            ]
        }
    ]
    names = [item["model_name"] for item in spec.model_list]
    assert names.count("narrador-gratis") == 1
    assert len(names) == len(set(names))
    assert spec.model_list[0]["litellm_params"]["model"] == DEFAULT_GEMINI_MODEL
    assert spec.model_list[1]["litellm_params"]["model"] == "gemini/gemini-3.1-flash-lite"
    assert spec.model_list[2]["litellm_params"]["model"] == "gemini/gemini-3.8-flash"
    assert spec.model_list[1]["litellm_params"]["api_key"] == spec.model_list[0]["litellm_params"]["api_key"]
    assert spec.model_list[2]["litellm_params"]["api_key"] == "gemini-key"
    assert spec.model_list[3]["litellm_params"]["model"].endswith(":free")
    assert spec.model_list[3]["litellm_params"]["model"] != "openrouter/free"
    assert "accounts/conta-cf/ai/v1" in spec.model_list[4]["litellm_params"]["api_base"]
    assert spec.model_list[4]["litellm_params"]["model"] == "cloudflare/@cf/meta/llama-3.1-8b-instruct-fast"
    assert spec.model_list[-1]["litellm_params"]["model"] == "groq/openai/gpt-oss-20b"
    assert "narrador-pago" not in spec.fallbacks[0]["narrador-gratis"]


def test_recusa_varias_chaves_e_roteador_aleatorio():
    with pytest.raises(ConfigError, match="uma conta"):
        load_settings({"GEMINI_API_KEY": "uma,duas"})
    with pytest.raises(ConfigError, match=":free"):
        build_spec(Settings(openrouter_api_key="chave", openrouter_model="openrouter/free"))
    with pytest.raises(ConfigError, match="conta"):
        build_spec(
            Settings(
                gemini_api_key="conta-a",
                paid_api_key="conta-b",
                paid_model=DEFAULT_GEMINI_MODEL,
            )
        )


def _reply(text, model):
    async def generate():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text))],
            model=model,
            usage=None,
        )

    return generate()


@pytest.mark.asyncio
async def test_stream_mudo_cai_para_sem_streaming_e_depois_para_o_outro_modelo():
    settings = Settings(gemini_api_key="gemini-secret")
    spec = build_spec(settings)
    calls = []

    async def complete(**kwargs):
        calls.append((kwargs["model"], kwargs["stream"], kwargs.get("reasoning_effort"), kwargs["timeout"]))
        assert kwargs["api_key"] == "gemini-secret"
        if kwargs["model"] == DEFAULT_GEMINI_MODEL:
            raise TimeoutError("Read timed out")
        if kwargs["stream"]:
            return _reply("Olá", kwargs["model"])
        raise AssertionError("o reserva não precisava desligar o streaming")

    async def nop(_remaining):
        return

    gateway = LiteLLMGateway(spec, settings, complete=complete, pause=nop)
    messages = [{"role": "user", "content": "memória e ficha"}]
    pieces = [piece async for piece in gateway.stream("free", messages)]
    assert pieces[0].text == "Olá"
    assert calls[0][0] == DEFAULT_GEMINI_MODEL and calls[0][1] is True
    assert calls[0][2] == "minimal"
    assert calls[0][3] == settings.first_token_seconds
    assert calls[1][0] == DEFAULT_GEMINI_MODEL and calls[1][1] is True
    assert calls[2] == (DEFAULT_GEMINI_MODEL, False, "minimal", settings.llm_timeout)
    assert calls[3][0] == "gemini/gemini-3.1-flash-lite" and calls[3][1] is True


@pytest.mark.asyncio
async def test_erro_do_provedor_nao_vaza_a_chave():
    settings = Settings(gemini_api_key="gemini-secret")
    spec = build_spec(settings)

    async def complete(**kwargs):
        raise RuntimeError("upstream gemini-secret failed")

    async def nop(_remaining):
        return

    gateway = LiteLLMGateway(spec, settings, complete=complete, pause=nop)
    with pytest.raises(NarratorUnavailable) as caught:
        async for _piece in gateway.stream("free", [{"role": "user", "content": "oi"}]):
            pass
    assert "gemini-secret" not in caught.value.message
    assert caught.value.public is False
    assert caught.value.reason == "Gemini: RuntimeError"


class _Unavailable(Exception):
    def __init__(self):
        super().__init__("UNAVAILABLE 503 high demand")
        self.status_code = 503


class MidStreamFallbackError(Exception):
    def __init__(self):
        inner = _Unavailable()
        super().__init__(f"litellm.MidStreamFallbackError: {inner}")
        self.original_exception = inner
        self.status_code = 503


def _ok_stream(model):
    async def generate():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Cena pronta"))],
            model=model,
            usage=None,
        )

    return generate()


@pytest.mark.asyncio
async def test_503_no_meio_do_stream_cai_para_o_proximo_modelo():
    settings = Settings(gemini_api_key="gemini-secret", turn_budget_seconds=5)
    spec = build_spec(settings)
    calls = []

    async def complete(**kwargs):
        calls.append((kwargs["model"], kwargs["stream"]))
        if kwargs["model"] == DEFAULT_GEMINI_MODEL and kwargs["stream"]:
            async def generate():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="ped"))],
                    model=kwargs["model"],
                    usage=None,
                )
                raise MidStreamFallbackError()

            return generate()
        if kwargs["model"] == DEFAULT_GEMINI_MODEL:
            raise MidStreamFallbackError()
        if kwargs["stream"]:
            return _ok_stream(kwargs["model"])
        raise AssertionError(kwargs["model"])

    async def nop(_remaining):
        return

    gateway = LiteLLMGateway(spec, settings, complete=complete, pause=nop)
    pieces = [piece async for piece in gateway.stream("free", [{"role": "user", "content": "oi"}])]
    assert "".join(piece.text for piece in pieces) == "Cena pronta"
    assert "ped" not in "".join(piece.text for piece in pieces)
    assert any(model == "gemini/gemini-3.1-flash-lite" for model, _stream in calls)
    assert calls[0] == (DEFAULT_GEMINI_MODEL, True)


@pytest.mark.asyncio
async def test_se_todos_falham_o_erro_e_amigavel_e_cabe_no_limite():
    settings = Settings(gemini_api_key="gemini-secret", turn_budget_seconds=0.4, first_token_seconds=0.05, llm_timeout=0.05)
    spec = build_spec(settings)

    async def complete(**kwargs):
        raise MidStreamFallbackError()

    async def nop(_remaining):
        return

    gateway = LiteLLMGateway(spec, settings, complete=complete, pause=nop)
    started = time.perf_counter()
    with pytest.raises(NarratorUnavailable) as caught:
        async for _piece in gateway.stream("free", [{"role": "user", "content": "oi"}]):
            pass
    elapsed = time.perf_counter() - started
    assert elapsed < 2
    assert player_failure_text(caught.value, settings) == OVERLOAD_MESSAGE
    assert "MidStream" not in player_failure_text(caught.value, settings)
    assert "sobrecarregado" in player_failure_text(caught.value, settings)


@pytest.mark.asyncio
async def test_resposta_so_com_estado_e_transitória_e_cai_no_proximo(caplog):
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    settings = Settings(gemini_api_key="gemini-secret", turn_budget_seconds=5)
    spec = build_spec(settings)
    calls = []

    async def complete(**kwargs):
        calls.append((kwargs["model"], kwargs["stream"]))
        if kwargs["model"] == DEFAULT_GEMINI_MODEL:
            if kwargs["stream"]:
                async def generate():
                    yield SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content='<estado>{"beat":"nada"}</estado>'),
                                finish_reason="stop",
                            )
                        ],
                        model=kwargs["model"],
                        usage=None,
                    )

                return generate()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='<estado>{"beat":"nada"}</estado>'),
                        finish_reason="length",
                    )
                ],
                model=kwargs["model"],
            )
        return _ok_stream(kwargs["model"]) if kwargs["stream"] else SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Cena pronta"), finish_reason="stop")],
            model=kwargs["model"],
        )

    async def nop(_remaining):
        return

    gateway = LiteLLMGateway(spec, settings, complete=complete, pause=nop)
    pieces = [piece async for piece in gateway.stream("free", [{"role": "user", "content": "oi"}])]
    assert "Cena pronta" in "".join(piece.text for piece in pieces)
    assert any(model != DEFAULT_GEMINI_MODEL for model, _stream in calls)
    assert "narrador resposta inutilizavel" in caplog.text
    assert "finish_reason=stop" in caplog.text or "finish_reason=length" in caplog.text


@pytest.mark.asyncio
async def test_json_vazio_com_stop_tenta_modelo_fallback_e_define_response_format():
    settings = Settings(
        gemini_api_key="gemini-secret",
        gemini_fallback_model="gemini-3.1-flash-lite",
        turn_budget_seconds=5,
    )
    spec = build_spec(settings)
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["max_tokens"] >= 1024
        if kwargs["model"] == DEFAULT_GEMINI_MODEL:
            if kwargs["stream"]:
                async def empty():
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=""), finish_reason="stop")],
                        model=kwargs["model"],
                        usage=None,
                    )

                return empty()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=""), finish_reason="stop")],
                model=kwargs["model"],
            )
        if kwargs["stream"]:
            async def valid():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content='{"arquetipo_id":"lutador_aura","confianca":0.9,"motivo":"aura"}'
                            ),
                            finish_reason="stop",
                        )
                    ],
                    model=kwargs["model"],
                    usage=None,
                )

            return valid()
        raise AssertionError("o JSON do fallback deveria ser válido")

    async def nop(_remaining):
        return

    gateway = LiteLLMGateway(spec, settings, complete=complete, pause=nop)
    pieces = [
        piece
        async for piece in gateway.stream(
            "free", [{"role": "user", "content": "lutador de aura"}], expect="json"
        )
    ]
    assert "lutador_aura" in "".join(piece.text for piece in pieces)
    assert any(call["model"] == "gemini/gemini-3.1-flash-lite" for call in calls)


def test_classifica_falha_do_provedor():
    assert classify_provider_error(RuntimeError("401 API key not valid"), "Gemini") == "Gemini: chave inválida"
    assert classify_provider_error(RuntimeError("model gemini-x was not found"), "Gemini") == "Gemini: modelo não encontrado"
    assert classify_provider_error(RuntimeError("429 rate limit exceeded"), "Gemini") == OVERLOAD_MESSAGE
    assert classify_provider_error(TimeoutError("Read timed out"), "Gemini") == OVERLOAD_MESSAGE


@pytest.mark.asyncio
async def test_check_llm_nao_imprime_chave(capsys, monkeypatch):
    async def probe(settings, attempt):
        assert attempt.api_key == "gemini-secret"
        return "ok"

    monkeypatch.setattr("app.check_llm.probe", probe)
    code = await check_run(Settings(gemini_api_key="gemini-secret"))
    output = capsys.readouterr().out
    assert code == 0
    assert DEFAULT_GEMINI_MODEL in output
    assert "gemini-3.1-flash-lite" in output
    assert "gemini-3.8-flash" in output
    assert "gemini-secret" not in output


def test_sobe_avisando_se_nao_ha_chave(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    log_startup(Settings())
    assert "gemini-3.5-flash-lite" in caplog.text
    assert "Nenhuma chave do pool grátis" in caplog.text
