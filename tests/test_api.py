import httpx
import pytest

from app.config import Settings
from app.factory import create_app
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
