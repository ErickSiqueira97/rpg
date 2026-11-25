"""Aplicação HTTP. O processo não guarda crônica: tudo vai para o banco."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.billing import ACTIVATED, CANCELED, WEBHOOK_CONTRACT, apply_billing_event
from app.config import Settings, load_settings
from app.db import Store
from app.gate import Gate
from app.llm import build_gateway, build_spec, log_startup
from app.missions import STARTER, mission_by_id
from app.moderation import Moderator
from app.narrator import GameEvent, Narrator, new_saga_world
from app.plans import daily_limit, day_key, days_left, effective_plan, next_reset_at
from app.catalog import origin_by_id, public_catalog, suggest_build
from app.engine.duel import archetype_profile, fight, profile_from_character
from app.engine.sheet import (
    apply_asi,
    apply_origin_bonus,
    blank_sheet,
    class_id_for,
    grant_xp,
    migrate_legacy,
    recompute_pe,
    training_xp_cap,
)
from app.engine.world import SHOP, buy, judgment, set_contract
from app.story import clean_line, validate_attributes

USERNAME = re.compile(r"^[A-Za-z0-9_\u00C0-\u024f]{3,24}$")
STATIC = "static"


def create_app(
    settings: Settings | None = None,
    now: Callable[[], int] | None = None,
    gateway: object | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    clock = now or (lambda: int(time.time()))
    store = Store(settings.database_path)
    gateway = gateway or build_gateway(settings)
    moderator = Moderator(settings.moderation, settings.moderation_terms, settings.moderation_webhook)
    gate = Gate(settings.max_concurrent, settings.max_waiting, settings.queue_wait_seconds)
    narrator = Narrator(store, gateway, gate, moderator, settings, clock)
    providers: list[str] = ["fake"] if settings.fake else list(build_spec(settings).providers)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_startup(settings)
        yield
        store.close()

    app = FastAPI(title="RPG Multiverso", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.gateway = gateway
    app.state.narrator = narrator
    app.state.now = clock
    app.state.providers = providers

    @app.get("/api/saude")
    async def saude():
        return {
            "ok": True,
            "falso": settings.fake,
            "provedores": providers,
            "rotaPaga": (not settings.fake and build_spec(settings).paid_entry is not None) or settings.fake,
        }

    @app.post("/api/cadastro")
    async def cadastro(request: Request):
        body = await _body(request)
        username, password, error = _credentials(body)
        if error:
            return error
        try:
            user, token = store.create_user(username, password, clock(), settings.trial_days)
        except sqlite3.IntegrityError:
            return _erro(409, "usuario_existente", "Esse usuário já existe.")
        return {"token": token, "jogador": _public_user(store, settings, user, clock())}

    @app.post("/api/entrar")
    async def entrar(request: Request):
        body = await _body(request)
        username, password, error = _credentials(body)
        if error:
            return error
        found = store.login(username, password, clock())
        if found is None:
            return _erro(401, "credenciais", "Usuário ou senha inválidos.")
        user, token = found
        return {"token": token, "jogador": _public_user(store, settings, user, clock())}

    @app.get("/api/eu")
    async def eu(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        return _public_user(store, settings, user, clock())

    @app.post("/api/personagens")
    async def criar_personagem(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        body = await _body(request)
        try:
            name = clean_line(body.get("nome"), 40, "Nome")
            origin = clean_line(body.get("origem"), 80, "Origem")
            archetype = clean_line(body.get("arquetipo"), 40, "Arquétipo")
            concept_raw = body.get("conceito") or ""
            concept = clean_line(concept_raw, 400, "Conceito") if str(concept_raw).strip() else ""
            attributes, sheet, archetype = _build_sheet(body, origin, archetype)
        except ValueError as exc:
            return _erro(400, "ficha", str(exc))
        character = store.create_character(user.id, name, origin, archetype, concept, attributes, clock(), sheet)
        return _public_character(character)

    @app.post("/api/professor")
    async def professor(request: Request):
        return await _treino(request, store, clock, settings, kind="professor")

    @app.post("/api/arena")
    async def arena(request: Request):
        return await _treino(request, store, clock, settings, kind="arena")

    @app.get("/api/taxas")
    async def taxas(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        return store.fight_rates()

    @app.get("/api/catalogo")
    async def catalogo():
        return public_catalog()

    @app.post("/api/quero")
    async def quero(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        body = await _body(request)
        build = suggest_build(str(body.get("texto") or ""))
        if build is None:
            return _erro(400, "quero", "Diga o que você quer ser, em uma frase.")
        return build

    @app.post("/api/personagens/{character_id}/subir")
    async def subir(character_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        character = store.get_character(user.id, character_id)
        if character is None:
            return _erro(404, "nao_encontrado", "Ficha não encontrada.")
        try:
            attributes, sheet = apply_asi(character.attributes, character.sheet or {}, await _body(request))
        except ValueError as exc:
            return _erro(400, "ficha", str(exc))
        character.attributes = attributes
        character.sheet = sheet
        store.update_character(character)
        return _public_character(character)

    @app.post("/api/personagens/{character_id}/rito")
    async def rito(character_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        character = store.get_character(user.id, character_id)
        if character is None:
            return _erro(404, "nao_encontrado", "Ficha não encontrada.")
        sheet = dict(character.sheet or {})
        stage = int(sheet.get("estagio") or 0)
        gates = (5, 11, 17)
        if stage >= 3:
            return _erro(400, "rito", "A linhagem já está no último estágio.")
        if int(sheet.get("nivel") or 1) < gates[stage] or not sheet.get("ritoPronto"):
            return _erro(400, "rito", "O rito abre depois de concluir uma missão já nesse nível.")
        sheet["estagio"] = stage + 1
        sheet["ritoPronto"] = False
        character.sheet = sheet
        store.update_character(character)
        return _public_character(character)

    @app.get("/api/personagens")
    async def listar_personagens(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        return _character_cards(store, user.id)

    @app.post("/api/sagas")
    async def criar_saga(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        body = await _body(request)
        character = store.get_character(user.id, str(body.get("personagemId") or ""))
        if character is None:
            return _erro(404, "nao_encontrado", "Ficha não encontrada.")
        requested = str(body.get("roteiroId") or "")
        if requested:
            script = mission_by_id(requested)
            if script is None:
                return _erro(404, "roteiro", "Missão desconhecida.")
        else:
            script = STARTER
        saga = store.create_saga(
            user.id,
            character,
            new_saga_world(character, script),
            clock(),
            title=script.title,
            kind=script.kind,
            script_id=script.id,
            recommended_level=script.recommended_level,
        )
        return saga

    @app.get("/api/sagas")
    async def listar_sagas(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        return store.list_sagas(user.id)

    @app.post("/api/sagas/{saga_id}/loja")
    async def loja(saga_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        memory = store.saga_memory(user.id, saga_id)
        if memory is None:
            return _erro(404, "nao_encontrado", "Saga não encontrada.")
        body = await _body(request)
        result = buy(memory["mundo"], str(body.get("item") or ""), str(clock()))
        if result["ok"]:
            store.save_world(user.id, saga_id, memory["mundo"])
        return {"ok": result["ok"], "linhas": result["linhas"], "mundo": memory["mundo"], "loja": list(SHOP)}

    @app.post("/api/sagas/{saga_id}/contrato")
    async def contrato(saga_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        memory = store.saga_memory(user.id, saga_id)
        if memory is None:
            return _erro(404, "nao_encontrado", "Saga não encontrada.")
        if (memory["mundo"].get("contrato") or {}).get("travado"):
            return _erro(400, "contrato", "O contrato desta cena já está travado.")
        stored = set_contract(memory["mundo"], await _body(request), memory.get("tipo") or "missao")
        store.save_world(user.id, saga_id, memory["mundo"])
        return {"contrato": stored}

    @app.post("/api/sagas/{saga_id}/julgamento")
    async def julgamento(saga_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        memory = store.saga_memory(user.id, saga_id)
        if memory is None:
            return _erro(404, "nao_encontrado", "Saga não encontrada.")
        character = store.get_character(user.id, memory["personagemId"])
        if character is None:
            return _erro(404, "nao_encontrado", "Ficha não encontrada.")
        result = judgment(character, memory["mundo"], saga_id)
        store.save_world(user.id, saga_id, memory["mundo"])
        return result

    @app.post("/api/sagas/{saga_id}/arquivar")
    async def arquivar_saga(saga_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        if not store.archive_saga(user.id, saga_id):
            return _erro(404, "nao_encontrado", "Saga não encontrada.")
        return {"ok": True}

    @app.get("/api/sagas/{saga_id}")
    async def obter_saga(saga_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        saga = store.get_saga(user.id, saga_id)
        if saga is None:
            return _erro(404, "nao_encontrado", "Saga não encontrada.")
        return saga

    @app.post("/api/sagas/{saga_id}/turnos")
    async def turno(saga_id: str, request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        body = await _body(request)
        abertura = bool(body.get("abertura"))
        texto = body.get("texto")
        events = narrator.play(user, saga_id, texto=texto if isinstance(texto, str) else None, abertura=abertura)
        accept = request.headers.get("accept", "")
        if "application/json" in accept and "text/event-stream" not in accept:
            return await _json_turn(events)
        return StreamingResponse(
            _sse(events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/billing/webhook")
    async def billing_webhook():
        return JSONResponse(status_code=501, content=WEBHOOK_CONTRACT)

    if settings.allow_dev_plan_toggle:

        @app.post("/api/dev/plano")
        async def dev_plano(request: Request):
            user = _user(request, store)
            if isinstance(user, JSONResponse):
                return user
            body = await _body(request)
            plan = body.get("plano")
            if plan not in {"paid", "free"}:
                return _erro(400, "plano", "Use plano paid ou free.")
            apply_billing_event(store, user.id, ACTIVATED if plan == "paid" else CANCELED)
            fresh = store.user_by_token(_token(request) or "")
            return _public_user(store, settings, fresh or user, clock())

    @app.get("/")
    async def index():
        return FileResponse(f"{STATIC}/index.html")

    @app.get("/changelog")
    async def changelog():
        return FileResponse(f"{STATIC}/changelog.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _public_user(store: Store, settings: Settings, user, moment: int) -> dict:
    plan = effective_plan(user.plan, user.trial_ends_at, moment)
    limit = daily_limit(plan, settings)
    return {
        "id": user.id,
        "usuario": user.username,
        "plano": plan,
        "planoGravado": user.plan,
        "testeAte": user.trial_ends_at,
        "diasDeTeste": days_left(user.trial_ends_at, moment) if plan == "trial" else 0,
        "turnosUsados": store.daily_turns(user.id, day_key(moment, settings.day_offset_hours)),
        "turnosLimite": limit,
        "resetEm": next_reset_at(moment, settings.day_offset_hours),
        "assinaturaUrl": settings.billing_checkout_url or None,
    }


async def _treino(request: Request, store: Store, clock, settings: Settings, *, kind: str):
    user = _user(request, store)
    if isinstance(user, JSONResponse):
        return user
    body = await _body(request)
    character = store.get_character(user.id, str(body.get("personagemId") or ""))
    if character is None:
        return _erro(404, "nao_encontrado", "Ficha não encontrada.")
    level = int(body.get("nivel") or (character.sheet or {}).get("nivel") or 1)
    if kind == "arena" and level not in {5, 11, 17}:
        return _erro(400, "arena", "A arena usa fichas no nível 5, 11 ou 17.")
    difficulty = str(body.get("dificuldade") or "padrao")
    if difficulty not in {"aprendiz", "padrao", "mestre"}:
        difficulty = "padrao"
    opponent = str(body.get("oponente") or "espelho")
    left = profile_from_character(character, level)
    if opponent == "espelho":
        right = profile_from_character(character, level)
        right["nome"] = "Espelho"
    elif opponent in {"tanque", "dano", "controle", "conjurador", "transformador"}:
        right = archetype_profile(opponent, level)
    else:
        return _erro(400, "oponente", "Oponente desconhecido.")
    result = fight(left, right, f"{user.id}|{clock()}|{kind}|{opponent}|{level}", difficulty)
    sheet = dict(character.sheet or {})
    gained = 0
    if kind == "professor" and result["vencedor"] == "jogador":
        day = day_key(clock(), settings.day_offset_hours)
        if sheet.get("treinoDia") != day:
            sheet["treinoDia"] = day
            sheet["treinoXp"] = 0
        room = training_xp_cap(int(sheet.get("nivel") or 1)) - int(sheet.get("treinoXp") or 0)
        gained = min(10, max(0, room))
        if gained:
            sheet = grant_xp(sheet, gained, character.attributes["vigor"])
            sheet["treinoXp"] = int(sheet.get("treinoXp") or 0) + gained
            sheet["treinoDia"] = day
            character.sheet = recompute_pe(sheet, character.attributes)
            store.update_character(character)
    store.record_fight(user.id, character.sheet or sheet, opponent, result["vencedor"], kind, clock())
    lines = list(result["linhas"])
    if body.get("aula"):
        lines.insert(0, "Aula: o d20 soma o bônus de ataque e compara com a CA. Abaixo da metade dos PV, quem luta defende em vez de atacar.")
    return {
        "vencedor": result["vencedor"],
        "rodadas": result["rodadas"],
        "linhas": lines[:12],
        "xp": gained,
        "nivel": level,
        "dificuldade": difficulty,
        "oponente": opponent,
    }


def _build_sheet(body: dict, origin: str, archetype: str) -> tuple[dict, dict, str]:
    raw = body.get("atributos") or {}
    class_name = str(body.get("classe") or archetype)
    class_id = class_id_for(class_name)
    origin_row = origin_by_id(str(body.get("origemId") or ""))
    values = {name: raw.get(name) for name in ("forca", "agilidade", "vigor", "percepcao", "intelecto", "essencia")}
    try:
        base = {name: int(value) for name, value in values.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("Atributos inválidos.") from exc
    if all(8 <= value <= 15 for value in base.values()):
        bonus = body.get("bonusOrigem") or {}
        if origin_row and bonus and any(name not in origin_row["atributos"] for name in bonus):
            raise ValueError("O bônus da origem só cai nos três atributos dela.")
        if bonus:
            attributes = apply_origin_bonus(base, bonus)
        elif origin_row:
            first, second = origin_row["atributos"][0], origin_row["atributos"][1]
            attributes = apply_origin_bonus(base, {first: 2, second: 1})
        else:
            attributes = apply_origin_bonus(base, {"vigor": 2, "forca": 1})
        sheet = blank_sheet(class_id, attributes)
        if origin_row:
            sheet["pericias"] = list(dict.fromkeys([*sheet["pericias"], *origin_row["pericias"]]))
            sheet["talento"] = origin_row["talento"]
    else:
        attributes = validate_attributes(base)
        attributes, sheet = migrate_legacy(attributes, class_name)
    sheet = recompute_pe(sheet, attributes)
    sheet["classeId"] = class_id
    if body.get("raca"):
        sheet["racaId"] = str(body.get("raca"))
    if body.get("via"):
        sheet["viaId"] = str(body.get("via"))
    if body.get("subclasse"):
        sheet["subclasse"] = str(body.get("subclasse"))[:60]
    if body.get("traco"):
        sheet["traco"] = str(body.get("traco"))[:40]
    if sheet.get("traco") == "nulo":
        sheet["viaId"] = ""
    if origin_row:
        sheet["origemId"] = origin_row["id"]
    return attributes, sheet, archetype


def _public_character(character) -> dict:
    sheet = character.sheet or {}
    vida_max = int(sheet.get("vidaMax") or 0) or max(1, 8 + int(character.attributes["vigor"]))
    return {
        "id": character.id,
        "nome": character.name,
        "origem": character.origin,
        "arquetipo": character.archetype,
        "conceito": character.concept,
        "atributos": character.attributes,
        "vida": vida_max,
        "vidaMax": vida_max,
        "nivel": sheet.get("nivel") or 1,
        "xp": sheet.get("xp") or 0,
        "peMax": sheet.get("peMax") or 0,
        "reserva": sheet.get("reserva") or "",
        "classeId": sheet.get("classeId") or "",
        "racaId": sheet.get("racaId") or "",
        "estagio": sheet.get("estagio") or 0,
        "pendente": bool(sheet.get("pendente")),
        "ficha": sheet,
    }


def _character_cards(store: Store, user_id: str) -> list[dict]:
    cards = [_public_character(item) for item in store.list_characters(user_id)]
    by_character: dict[str, dict] = {}
    for saga in store.list_sagas(user_id):
        if saga["vazia"] or saga["personagemId"] in by_character:
            continue
        by_character[saga["personagemId"]] = saga
    for card in cards:
        latest = by_character.get(card["id"])
        if latest and latest.get("vida") is not None:
            card["vida"] = latest["vida"]
            card["vidaMax"] = latest.get("vidaMax") or card["vidaMax"]
    return cards


def _token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header[7:].strip() or None


def _user(request: Request, store: Store):
    token = _token(request)
    if not token:
        return _erro(401, "auth", "Faça login.")
    user = store.user_by_token(token)
    if user is None:
        return _erro(401, "auth", "Sessão inválida. Entre de novo.")
    return user


def _credentials(body: dict):
    username = str(body.get("usuario") or "")
    password = str(body.get("senha") or "")
    if not USERNAME.match(username):
        return None, None, _erro(400, "usuario", "Usuário: 3 a 24 letras, números ou _.")
    if not 6 <= len(password) <= 72:
        return None, None, _erro(400, "senha", "Senha: 6 a 72 caracteres.")
    return username, password, None


def _erro(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"codigo": code, "mensagem": message})


async def _body(request: Request) -> dict:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def _json_turn(events: AsyncIterator[GameEvent]) -> JSONResponse:
    response = _erro(503, "narrador", "Sem resposta do narrador.")
    try:
        async for event in events:
            if event.type == "done":
                response = JSONResponse(content=event.data)
                break
            if event.type in {"erro", "cota"}:
                response = JSONResponse(status_code=event.status, content=event.data)
                break
    finally:
        await events.aclose()
    return response


async def _sse(events: AsyncIterator[GameEvent]):
    try:
        async for event in events:
            yield f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"
    finally:
        await events.aclose()
