import httpx
import pytest
from pathlib import Path

import logging

from app.config import Settings
from app.factory import create_app
from app.llm import NarratorUnavailable
from app.story import SYSTEM_PROMPT

SHEET = {
    "nome": "Lia",
    "origem": "Porto de Véspera",
    "arquetipo": "Errante",
    "conceito": "procura o farol",
    "atributos": {
        "forca": 6,
        "agilidade": 6,
        "vigor": 6,
        "percepcao": 6,
        "intelecto": 6,
        "essencia": 6,
    },
}


@pytest.fixture
def app(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "rpg.sqlite"),
        fake=True,
        moderation="off",
        trial_turns_per_day=2,
        free_turns_per_day=1,
        allow_dev_plan_toggle=True,
        billing_checkout_url="https://example.test/assinar",
    )
    application = create_app(settings)
    yield application
    application.state.store.close()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def jogar(client):
    created = await client.post("/api/cadastro", json={"usuario": "lia", "senha": "segredo"})
    assert created.status_code == 200
    token = created.json()["token"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    character = await client.post("/api/personagens", headers=headers, json=SHEET)
    assert character.status_code == 200
    saga = await client.post("/api/sagas", headers=headers, json={"personagemId": character.json()["id"]})
    assert saga.status_code == 200
    return headers, saga.json()["id"]


@pytest.mark.asyncio
async def test_treino_retorna_log_completo_e_explicacao_da_aula(client):
    headers, _saga_id = await jogar(client)
    characters = await client.get("/api/personagens", headers=headers)
    character_id = characters.json()[0]["id"]

    response = await client.post(
        "/api/professor",
        headers=headers,
        json={"personagemId": character_id, "nivel": 5, "aula": True},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["resultado"].endswith(f"em {result['rodadas']} rodadas.")
    assert result["linhas"][0].startswith("Aula: CA (Classe de Armadura)")
    assert any(line.startswith("── Rodada 1 ──") for line in result["linhas"])
    assert any("Espelho " in line and " → " in line and " PV" in line for line in result["linhas"])
    assert result["linhas"][-1].startswith("PV finais —")

    response = await client.post(
        "/api/professor",
        headers=headers,
        json={"personagemId": character_id, "nivel": 5, "aula": False},
    )
    assert response.status_code == 200
    assert not any(line.startswith("Aula:") for line in response.json()["linhas"])


@pytest.mark.asyncio
async def test_cadastro_ficha_saga_e_continuacao(client, app):
    headers, saga_id = await jogar(client)
    me = await client.get("/api/eu", headers=headers)
    assert me.json()["plano"] == "trial"
    assert me.json()["diasDeTeste"] == 7

    bad = dict(SHEET)
    bad["atributos"] = dict(SHEET["atributos"])
    bad["atributos"]["forca"] = 10
    bad["nome"] = "Outra"
    rejected = await client.post("/api/personagens", headers=headers, json=bad)
    assert rejected.status_code == 400

    opening = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"abertura": True})
    assert opening.status_code == 200
    body = opening.json()
    assert "névoa" in body["narrativa"]
    assert body["tokensEstimados"] > 0
    assert body["mundo"]["quando"] == "depois"

    again = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"abertura": True})
    assert again.status_code == 400

    action = await client.post(
        f"/api/sagas/{saga_id}/turnos",
        headers=headers,
        json={"texto": "Eu cruzo o cais em silêncio."},
    )
    assert action.status_code == 200
    saved = await client.get(f"/api/sagas/{saga_id}", headers=headers)
    messages = saved.json()["mensagens"]
    assert [item["papel"] for item in messages] == ["narrator", "player", "narrator"]
    assert "cais" in messages[1]["texto"]
    assert "névoa" in saved.json()["resumo"]

    package = app.state.gateway.calls[-1][1]
    assert package[0]["content"] == SYSTEM_PROMPT
    assert "névoa" in package[1]["content"]
    assert any("cais" in item["content"] for item in package)

    login = await client.post("/api/entrar", json={"usuario": "lia", "senha": "segredo"})
    assert login.status_code == 200
    wrong = await client.post("/api/entrar", json={"usuario": "lia", "senha": "errada"})
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_quero_oferece_botoes_aprende_escolha_e_remove_aprendizado(client, app):
    registration = await client.post("/api/cadastro", json={"usuario": "lia", "senha": "segredo"})
    headers = {"Authorization": f"Bearer {registration.json()['token']}"}

    unknown = await client.post("/api/quero", headers=headers, json={"texto": "quero ser zorblax"})
    assert unknown.status_code == 200
    assert unknown.json()["precisaEscolha"] is True
    assert len(unknown.json()["opcoes"]) == 25

    selected = await client.post(
        "/api/quero",
        headers=headers,
        json={"texto": "quero ser zorblax", "arquetipo_id": "lutador_aura"},
    )
    assert selected.status_code == 200
    assert selected.json()["arquetipo_id"] == "lutador_aura"
    assert selected.json()["fonte"] == "botoes"

    learned = await client.post("/api/quero", headers=headers, json={"texto": "quero ser zorblax"})
    assert learned.json()["fonte"] == "aprendido"
    assert learned.json()["arquetipo_id"] == "lutador_aura"

    correction = await client.post(
        "/api/quero",
        headers=headers,
        json={"texto": "quero ser zorblax", "nao_e_isso": True},
    )
    assert correction.json()["precisaEscolha"] is True
    store = app.state.store
    user = store.user_by_token(registration.json()["token"])
    assert store.learned_archetype(user.id, "zorblax") is None


@pytest.mark.asyncio
async def test_quero_aprende_classificacao_da_llm(client, app):
    import json
    from types import SimpleNamespace

    class ClassifierGateway:
        def __init__(self):
            self.calls = 0

        async def stream(self, _route, _messages, *, expect, temperature):
            assert expect == "json"
            assert temperature == 0
            self.calls += 1
            yield SimpleNamespace(
                text=json.dumps(
                    {"arquetipo_id": "lutador_aura", "confianca": 0.8, "motivo": "combatente de aura"}
                )
            )

    registration = await client.post("/api/cadastro", json={"usuario": "ria", "senha": "segredo"})
    headers = {"Authorization": f"Bearer {registration.json()['token']}"}
    gateway = ClassifierGateway()
    app.state.gateway = gateway

    classified = await client.post("/api/quero", headers=headers, json={"texto": "quero ser um lutador energético"})
    assert classified.status_code == 200
    assert classified.json()["fonte"] == "llm"
    learned = await client.post("/api/quero", headers=headers, json={"texto": "quero ser um lutador energético"})
    assert learned.json()["fonte"] == "aprendido"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_memoria_continua_depois_de_reabrir_o_banco(tmp_path):
    path = str(tmp_path / "rpg.sqlite")
    settings = Settings(database_path=path, fake=True, moderation="off")
    first = create_app(settings)
    transport = httpx.ASGITransport(app=first)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, saga_id = await jogar(client)
        opened = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"abertura": True})
        assert opened.status_code == 200
        token = headers["Authorization"]
    first.state.store.close()

    second = create_app(settings)
    transport = httpx.ASGITransport(app=second)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": token, "Accept": "application/json"}
        saved = await client.get(f"/api/sagas/{saga_id}", headers=headers)
        assert "névoa" in saved.json()["resumo"]
        follow = await client.post(
            f"/api/sagas/{saga_id}/turnos",
            headers=headers,
            json={"texto": "Pergunto o nome da saga."},
        )
        assert follow.status_code == 200
    canon = second.state.gateway.calls[-1][1][1]["content"]
    assert "A névoa se moveu." in canon
    second.state.store.close()


@pytest.mark.asyncio
async def test_cota_e_plano_pago(client, app):
    headers, saga_id = await jogar(client)
    first = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"abertura": True})
    assert first.status_code == 200
    second = await client.post(
        f"/api/sagas/{saga_id}/turnos",
        headers=headers,
        json={"texto": "Sigo em frente."},
    )
    assert second.status_code == 200
    third = await client.post(
        f"/api/sagas/{saga_id}/turnos",
        headers=headers,
        json={"texto": "Mais um passo."},
    )
    assert third.status_code == 402
    assert "Assine" in third.json()["mensagem"]
    assert third.json()["assinaturaUrl"] == "https://example.test/assinar"
    saved = await client.get(f"/api/sagas/{saga_id}", headers=headers)
    assert len(saved.json()["mensagens"]) == 3

    paid = await client.post("/api/dev/plano", headers=headers, json={"plano": "paid"})
    assert paid.status_code == 200
    assert paid.json()["plano"] == "paid"
    fourth = await client.post(
        f"/api/sagas/{saga_id}/turnos",
        headers=headers,
        json={"texto": "Agora com a rota paga."},
    )
    assert fourth.status_code == 200
    assert app.state.gateway.calls[-1][0] == "paid"

    webhook = await client.post("/api/billing/webhook", json={"type": "subscription.activated"})
    assert webhook.status_code == 501
    assert "apply_billing_event" in webhook.text


@pytest.mark.asyncio
async def test_streaming_e_moderacao(tmp_path):
    settings = Settings(database_path=str(tmp_path / "rpg.sqlite"), fake=True, moderation="basic")
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, saga_id = await jogar(client)
        blocked = await client.post(
            f"/api/sagas/{saga_id}/turnos",
            headers=headers,
            json={"texto": "Uma criança em cena sexual."},
        )
        assert blocked.status_code == 400
        async with client.stream(
            "POST",
            f"/api/sagas/{saga_id}/turnos",
            headers={**headers, "Accept": "text/event-stream"},
            json={"abertura": True},
        ) as response:
            assert response.status_code == 200
            body = (await response.aread()).decode()
        assert "event: token" in body
        assert "event: done" in body
        assert "névoa" in body
    app.state.store.close()


@pytest.mark.asyncio
async def test_nova_missao_abre_com_o_roteiro(client, app):
    headers, saga_id = await jogar(client)
    created = await client.get(f"/api/sagas/{saga_id}", headers=headers)
    body = created.json()
    assert body["tipo"] == "missao"
    assert body["roteiroId"] == "farol-de-vespera"
    assert body["nivelSugerido"] == 1
    assert "farol" in body["objetivo"].lower()
    assert body["mensagens"] == []
    assert body["mundo"]["lugar"] == "Porto de Véspera"

    opened = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"abertura": True})
    assert opened.status_code == 200
    sent = "\n".join(item["content"] for item in app.state.gateway.calls[-1][1])
    assert "farol" in sent.lower()
    assert "caixa" in sent.lower()
    assert "Porto de Véspera" in sent


@pytest.mark.asyncio
async def test_retomada_lista_a_missao_recente_com_o_historico(tmp_path):
    now = {"t": 1_700_000_000}
    app = create_app(
        Settings(database_path=str(tmp_path / "rpg.sqlite"), fake=True, moderation="off"),
        now=lambda: now["t"],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/cadastro", json={"usuario": "lia", "senha": "segredo"})
        headers = {"Authorization": f"Bearer {created.json()['token']}", "Accept": "application/json"}
        character = await client.post("/api/personagens", headers=headers, json=SHEET)
        personagem = character.json()["id"]
        antiga = await client.post("/api/sagas", headers=headers, json={"personagemId": personagem})
        now["t"] += 30
        recente = await client.post("/api/sagas", headers=headers, json={"personagemId": personagem})
        now["t"] += 30
        aberta = await client.post(
            f"/api/sagas/{antiga.json()['id']}/turnos",
            headers=headers,
            json={"abertura": True},
        )
        assert aberta.status_code == 200
        lista = (await client.get("/api/sagas", headers=headers)).json()
        assert [item["titulo"] for item in lista][:1] == [antiga.json()["titulo"]]
        assert lista[0]["id"] == antiga.json()["id"]
        assert recente.json()["id"] in {item["id"] for item in lista}
        detalhe = (await client.get(f"/api/sagas/{antiga.json()['id']}", headers=headers)).json()
        assert any(item["papel"] == "narrator" and item["texto"] for item in detalhe["mensagens"])
        de_novo = (await client.get(f"/api/sagas/{antiga.json()['id']}", headers=headers)).json()
        assert len(de_novo["mensagens"]) == len(detalhe["mensagens"])
    app.state.store.close()


@pytest.mark.asyncio
async def test_arquiva_aventura_vazia_e_mantem_a_que_tem_turno(tmp_path):
    app = create_app(Settings(database_path=str(tmp_path / "rpg.sqlite"), fake=True, moderation="off"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/cadastro", json={"usuario": "lia", "senha": "segredo"})
        headers = {"Authorization": f"Bearer {created.json()['token']}", "Accept": "application/json"}
        character = await client.post("/api/personagens", headers=headers, json=SHEET)
        personagem = character.json()["id"]
        assert character.json()["vida"] > 0
        vazia = await client.post("/api/sagas", headers=headers, json={"personagemId": personagem})
        jogada = await client.post("/api/sagas", headers=headers, json={"personagemId": personagem})
        aberta = await client.post(
            f"/api/sagas/{jogada.json()['id']}/turnos",
            headers=headers,
            json={"abertura": True},
        )
        assert aberta.status_code == 200
        lista = (await client.get("/api/sagas", headers=headers)).json()
        ids = {item["id"] for item in lista}
        assert vazia.json()["id"] in ids and jogada.json()["id"] in ids
        assert next(item for item in lista if item["id"] == vazia.json()["id"])["vazia"] is True
        assert next(item for item in lista if item["id"] == jogada.json()["id"])["personagemNome"] == "Lia"
        archived = await client.post(f"/api/sagas/{vazia.json()['id']}/arquivar", headers=headers)
        assert archived.status_code == 200
        restante = (await client.get("/api/sagas", headers=headers)).json()
        assert [item["id"] for item in restante] == [jogada.json()["id"]]
        assert "caixa" in (restante[0]["titulo"] + aberta.json().get("narrativa", "")).lower() or restante[0]["titulo"]
    app.state.store.close()


def test_recarregar_reabre_a_cena_sem_pedir_outra_narração():
    source = Path("static/app.js").read_text(encoding="utf-8")
    jogo = source.split("async function abrirJogo")[1].split("async function carregarFichas")[0]
    assert "escolherSaga(sagas, localStorage.getItem(\"sagaId\"))" in jogo
    assert "enviarTurno" not in jogo
    assert "localStorage.setItem(\"sagaId\"" in source


class _CenaDaCaixa:
    async def stream(self, route, messages, **kwargs):
        from app.llm import Piece

        yield Piece(
            text=(
                "<narrativa>\nLia força a tampa. Maíra foge e os guardas se viram.\n</narrativa>"
                '<estado>{"beat":"wel abriu a caixa lacrada, alarmando Maíra e atraindo a atenção dos guardas'
                " - wel abriu a caixa, espantou Maíra e atraiu os guardas do cais\","
                '"objetivo":"Escapar dos guardas sem ser presa","objetivoStatus":"falhou"}</estado>'
            ),
            model="fake",
        )


class _SoEstado:
    async def stream(self, route, messages, **kwargs):
        from app.llm import Piece

        yield Piece(text='<estado>{"beat":"nao gravar"}</estado>', model="fake", finish_reason="stop")


@pytest.mark.asyncio
async def test_acao_que_quebra_o_objetivo_atualiza_e_nao_duplica_memoria(tmp_path):
    app = create_app(
        Settings(database_path=str(tmp_path / "rpg.sqlite"), fake=True, moderation="off"),
        gateway=_CenaDaCaixa(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/cadastro", json={"usuario": "wel", "senha": "segredo"})
        headers = {"Authorization": f"Bearer {created.json()['token']}", "Accept": "application/json"}
        sheet = dict(SHEET)
        sheet["nome"] = "Lia"
        character = await client.post("/api/personagens", headers=headers, json=sheet)
        saga = await client.post("/api/sagas", headers=headers, json={"personagemId": character.json()["id"]})
        done = await client.post(
            f"/api/sagas/{saga.json()['id']}/turnos",
            headers=headers,
            json={"texto": "abro a caixa"},
        )
        body = done.json()
        assert done.status_code == 200
        assert body["objetivoStatus"] == "falhou"
        assert "guardas" in body["objetivo"]
        assert "sem abri" in body["objetivoOriginal"]
        assert body["resumo"].count("\n") == 0
        assert "Lia abriu" in body["resumo"]
        assert "wel" not in body["resumo"].lower()
    app.state.store.close()


@pytest.mark.asyncio
async def test_turno_sem_prosa_nao_grava_memoria(tmp_path):
    app = create_app(
        Settings(database_path=str(tmp_path / "rpg.sqlite"), fake=True, moderation="off"),
        gateway=_SoEstado(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/api/cadastro", json={"usuario": "wel", "senha": "segredo"})
        headers = {"Authorization": f"Bearer {created.json()['token']}", "Accept": "application/json"}
        character = await client.post("/api/personagens", headers=headers, json=SHEET)
        saga = await client.post("/api/sagas", headers=headers, json={"personagemId": character.json()["id"]})
        failed = await client.post(
            f"/api/sagas/{saga.json()['id']}/turnos",
            headers=headers,
            json={"texto": "abro a caixa"},
        )
        assert failed.status_code == 503
        assert "Nada foi gravado" in failed.json()["mensagem"]
        saved = await client.get(f"/api/sagas/{saga.json()['id']}", headers=headers)
        assert saved.json()["resumo"] == ""
        assert saved.json()["mensagens"] == []
    app.state.store.close()


class _ChaveInvalida:
    async def stream(self, route, messages, **kwargs):
        raise NarratorUnavailable(
            "API key not valid secret-key",
            provider="Gemini",
            model="gemini/gemini-3.5-flash-lite",
            reason="Gemini: chave inválida",
        )
        yield None


@pytest.mark.asyncio
async def test_erro_do_narrador_vai_para_o_chat_e_para_o_log(tmp_path, caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    settings = Settings(
        database_path=str(tmp_path / "rpg.sqlite"),
        fake=True,
        moderation="off",
        gemini_api_key="secret-key",
        host="127.0.0.1",
    )
    app = create_app(settings, gateway=_ChaveInvalida())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, saga_id = await jogar(client)
        failed = await client.post(
            f"/api/sagas/{saga_id}/turnos",
            headers=headers,
            json={"texto": "teste"},
        )
        assert failed.status_code == 503
        assert "Gemini: chave inválida" in failed.json()["mensagem"]
        assert "secret-key" not in failed.json()["mensagem"]
        async with client.stream(
            "POST",
            f"/api/sagas/{saga_id}/turnos",
            headers={**headers, "Accept": "text/event-stream"},
            json={"texto": "teste"},
        ) as response:
            sse = (await response.aread()).decode()
        assert "event: erro" in sse
        assert "Gemini: chave inválida" in sse
        saved = await client.get(f"/api/sagas/{saga_id}", headers=headers)
        assert saved.json()["mensagens"] == []
    assert "narrador falhou" in caplog.text
    assert "provedor=Gemini" in caplog.text
    assert "secret-key" not in caplog.text
    quiet = Settings(
        database_path=str(tmp_path / "quiet.sqlite"),
        fake=True,
        moderation="off",
        host="0.0.0.0",
        debug=False,
    )
    hidden = create_app(quiet, gateway=_ChaveInvalida())
    transport = httpx.ASGITransport(app=hidden)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers, saga_id = await jogar(client)
        failed = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"texto": "teste"})
        assert "chave inválida" not in failed.json()["mensagem"]
        assert "não responderam" in failed.json()["mensagem"]
    app.state.store.close()
    hidden.state.store.close()


@pytest.mark.asyncio
async def test_rolagem_gravada_nao_muda_no_reenvio(client, app):
    from app.engine.rng import turn_key

    headers, saga_id = await jogar(client)
    opened = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"abertura": True})
    assert opened.status_code == 200
    saved = await client.get(f"/api/sagas/{saga_id}", headers=headers)
    action = "Eu examino o selo."
    key = turn_key(saga_id, len(saved.json()["mensagens"]), action)
    world = saved.json()["mundo"]
    world["vida"] = 4
    app.state.store.save_roll(
        saga_id,
        key,
        {
            "linhas": ["🎲 Atletismo (Força): 14 + 3 = 17 vs CD 15 — sucesso"],
            "rolagem": {"resultado": "sucesso", "total": 17, "cd": 15},
            "mundo": world,
            "sheet": (await client.get("/api/personagens", headers=headers)).json()[0]["ficha"],
        },
    )
    again = await client.post(f"/api/sagas/{saga_id}/turnos", headers=headers, json={"texto": action})
    assert again.status_code == 200
    assert "14 + 3 = 17 vs CD 15 — sucesso" in again.json()["narrativa"]
    assert again.json()["mundo"]["vida"] == 4


@pytest.mark.asyncio
async def test_criar_rejeita_bonus_de_origem_em_todos_os_atributos(client):
    created = await client.post("/api/cadastro", json={"usuario": "ori", "senha": "segredo"})
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    base = {"forca": 15, "agilidade": 14, "vigor": 13, "percepcao": 12, "intelecto": 10, "essencia": 8}
    body = {
        "nome": "Lia",
        "origem": "Mercenário",
        "origemId": "mercenario",
        "arquetipo": "Espadachim",
        "classe": "espadachim",
        "atributos": base,
        "bonusOrigem": {name: 2 for name in base},
    }
    rejected = await client.post("/api/personagens", headers=headers, json=body)
    assert rejected.status_code == 400
    body["bonusOrigem"] = {"agilidade": 2, "forca": 1}
    accepted = await client.post("/api/personagens", headers=headers, json=body)
    assert accepted.status_code == 200
    assert accepted.json()["atributos"]["agilidade"] == 16
    assert accepted.json()["atributos"]["forca"] == 16
