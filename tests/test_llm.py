from types import SimpleNamespace

import pytest

from app.config import ConfigError, Settings, load_settings
from app.llm import LiteLLMGateway, NarratorUnavailable, build_spec


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
    assert spec.fallbacks == [{"narrador-gratis": ["narrador-openrouter", "narrador-cloudflare"]}]
    names = [item["model_name"] for item in spec.model_list]
    assert names.count("narrador-gratis") == 1
    assert len(names) == len(set(names))
    assert spec.model_list[0]["litellm_params"]["model"] == "gemini/gemini-2.5-flash-lite"
    assert spec.model_list[1]["litellm_params"]["model"].endswith(":free")
    assert spec.model_list[1]["litellm_params"]["model"] != "openrouter/free"
    assert "accounts/conta-cf/ai/v1" in spec.model_list[2]["litellm_params"]["api_base"]
    assert spec.model_list[2]["litellm_params"]["model"] == "cloudflare/@cf/meta/llama-3.1-8b-instruct-fast"
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
                paid_model="gemini/gemini-2.5-flash-lite",
            )
        )


@pytest.mark.asyncio
async def test_gateway_chama_o_router_com_o_mesmo_pacote(monkeypatch):
    settings = Settings(gemini_api_key="gemini-secret", openrouter_api_key="or-secret")
    spec = build_spec(settings)
    calls = {}

    class FakeRouter:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        async def acompletion(self, **kwargs):
            calls["req"] = kwargs

            async def generate():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Olá"))],
                    model="gemini/gemini-2.5-flash-lite",
                    usage=None,
                )

            return generate()

    monkeypatch.setattr("litellm.Router", FakeRouter)
    gateway = LiteLLMGateway(spec, settings)
    messages = [
        {"role": "system", "content": "prompt fixo"},
        {"role": "user", "content": "memória e ficha"},
    ]
    pieces = [piece async for piece in gateway.stream("free", messages)]
    assert calls["init"]["num_retries"] == 0
    assert calls["init"]["fallbacks"] == spec.fallbacks
    assert calls["init"]["model_list"] == spec.model_list
    assert calls["req"]["model"] == "narrador-gratis"
    assert calls["req"]["messages"] == messages
    assert pieces[0].text == "Olá"


@pytest.mark.asyncio
async def test_erro_do_provedor_nao_vaza_a_chave(monkeypatch):
    settings = Settings(gemini_api_key="gemini-secret")
    spec = build_spec(settings)

    class FakeRouter:
        def __init__(self, **kwargs):
            pass

        async def acompletion(self, **kwargs):
            raise RuntimeError("upstream gemini-secret failed")

    monkeypatch.setattr("litellm.Router", FakeRouter)
    gateway = LiteLLMGateway(spec, settings)
    with pytest.raises(NarratorUnavailable) as caught:
        async for _piece in gateway.stream("free", [{"role": "user", "content": "oi"}]):
            pass
    assert "gemini-secret" not in caught.value.message
    assert caught.value.public is False
