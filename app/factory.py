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
            attributes = validate_attributes(body.get("atributos"))
        except ValueError as exc:
            return _erro(400, "ficha", str(exc))
        character = store.create_character(user.id, name, origin, archetype, concept, attributes, clock())
        return _public_character(character)

    @app.get("/api/personagens")
    async def listar_personagens(request: Request):
        user = _user(request, store)
        if isinstance(user, JSONResponse):
            return user
        return [_public_character(item) for item in store.list_characters(user.id)]

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


def _public_character(character) -> dict:
    return {
        "id": character.id,
        "nome": character.name,
        "origem": character.origin,
        "arquetipo": character.archetype,
        "conceito": character.concept,
        "atributos": character.attributes,
    }


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
