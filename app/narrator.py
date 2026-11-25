"""Um turno: cota, moderação, pacote de contexto, LiteLLM, gravação."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from app.config import Settings
from app.db import Store
from app.gate import Gate, GateFull, GateTimeout
from app.llm import NarratorUnavailable, log_narrator_failure, player_failure_text
from app.missions import format_script, mission_by_id, opening_command
from app.moderation import Moderator
from app.plans import daily_limit, day_key, effective_plan, llm_route, next_reset_at
from app.story import (
    Character,
    NarrativeExtractor,
    StoryMessage,
    apply_patch,
    assemble_context,
    estimate_tokens,
    initial_world,
    parse_narration,
    update_summary,
    use_character_name,
)


@dataclass
class GameEvent:
    type: str
    data: dict
    status: int = 200


class Narrator:
    def __init__(
        self,
        store: Store,
        gateway,
        gate: Gate,
        moderator: Moderator,
        settings: Settings,
        now: Callable[[], int] | None = None,
    ):
        self.store = store
        self.gateway = gateway
        self.gate = gate
        self.moderator = moderator
        self.settings = settings
        self.now = now or (lambda: int(time.time()))
        self._busy: set[str] = set()

    async def play(self, user, saga_id: str, *, texto: str | None, abertura: bool) -> AsyncIterator[GameEvent]:
        if user.id in self._busy:
            yield GameEvent(
                "erro",
                {"codigo": "ocupado", "mensagem": "Você já tem um turno em andamento."},
                429,
            )
            return
        memory = self.store.saga_memory(user.id, saga_id)
        if memory is None:
            yield GameEvent("erro", {"codigo": "nao_encontrado", "mensagem": "Saga não encontrada."}, 404)
            return
        character = self.store.get_character(user.id, memory["personagemId"])
        if character is None:
            yield GameEvent("erro", {"codigo": "nao_encontrado", "mensagem": "Ficha não encontrada."}, 404)
            return
        if abertura and memory["mensagens"]:
            yield GameEvent(
                "erro",
                {"codigo": "ja_comecou", "mensagem": "A saga já começou. Escreva o que você faz."},
                400,
            )
            return
        mission = mission_by_id(memory.get("roteiroId"))
        script_text = format_script(mission) if mission else ""
        player_text = None
        if abertura:
            action = opening_command(mission)
        else:
            player_text = " ".join((texto or "").split())
            if not player_text:
                yield GameEvent("erro", {"codigo": "acao_vazia", "mensagem": "Escreva o que você faz."}, 400)
                return
            if len(player_text) > 1500:
                yield GameEvent("erro", {"codigo": "acao_longa", "mensagem": "A ação pode ter até 1500 caracteres."}, 400)
                return
            refusal = await self.moderator.check(player_text, "input")
            if refusal:
                yield GameEvent("erro", {"codigo": "moderacao", "mensagem": refusal}, 400)
                return
            action = f"<acao_do_jogador>\n{player_text}\n</acao_do_jogador>"

        now = self.now()
        plan = effective_plan(user.plan, user.trial_ends_at, now)
        route = llm_route(plan)
        self._busy.add(user.id)
        consumed = False
        saved = False
        day = day_key(now, self.settings.day_offset_hours)
        try:
            async with self.gate:
                limit = daily_limit(plan, self.settings)
                allowed, used = self.store.consume_turn(user.id, day, limit)
                if not allowed:
                    yield self._quota(plan, used, limit, now)
                    return
                consumed = True
                package = assemble_context(
                    character=character,
                    world=memory["mundo"],
                    summary=memory["resumo"],
                    recent=[StoryMessage(item["role"], item["content"]) for item in memory["mensagens"]],
                    action=action,
                    script=script_text,
                    max_recent=self.settings.max_recent,
                    max_context_tokens=self.settings.max_context_tokens,
                    summary_max_tokens=self.settings.summary_max_tokens,
                    message_max_tokens=self.settings.message_max_tokens,
                )
                raw: list[str] = []
                extractor = NarrativeExtractor()
                model = ""
                provider_prompt = None
                provider_completion = None
                try:
                    async for piece in self.gateway.stream(route, package.messages):
                        if piece.model:
                            model = piece.model
                        if piece.prompt_tokens is not None:
                            provider_prompt = piece.prompt_tokens
                        if piece.completion_tokens is not None:
                            provider_completion = piece.completion_tokens
                        if piece.text:
                            raw.append(piece.text)
                            prose = extractor.push(piece.text)
                            if prose:
                                yield GameEvent("token", {"texto": prose})
                except NarratorUnavailable as exc:
                    log_narrator_failure(exc, self.settings.secrets)
                    yield GameEvent(
                        "erro",
                        {"codigo": "narrador", "mensagem": player_failure_text(exc, self.settings)},
                        503,
                    )
                    return
                parsed = parse_narration("".join(raw))
                if not parsed.narrative.strip():
                    yield GameEvent(
                        "erro",
                        {"codigo": "narrador", "mensagem": "O narrador não devolveu uma cena. Nada foi gravado."},
                        503,
                    )
                    return
                output_refusal = await self.moderator.check(parsed.narrative, "output")
                narrative = parsed.narrative if output_refusal is None else (
                    "A cena se fecha antes de mostrar isso. Tente outra ação."
                )
                narrative = use_character_name(narrative, character.name, user.username)
                if output_refusal is not None:
                    yield GameEvent("troca", {"texto": narrative})
                world = apply_patch(memory["mundo"], parsed.patch if output_refusal is None else {})
                beat = parsed.beat if output_refusal is None else "A cena foi interrompida."
                beat = use_character_name(beat, character.name, user.username)
                summary = update_summary(memory["resumo"], beat, self.settings.summary_max_tokens)
                title = memory["titulo"]
                saga_name = world.get("saga")
                if saga_name and saga_name != "a revelar":
                    title = str(saga_name)[:80]
                self.store.save_turn(
                    user_id=user.id,
                    saga_id=saga_id,
                    player_text=player_text,
                    narrative=narrative,
                    world=world,
                    summary=summary,
                    title=title,
                    route=route,
                    model=model or route,
                    estimated_prompt_tokens=package.estimated_tokens,
                    estimated_completion_tokens=estimate_tokens(narrative),
                    provider_prompt_tokens=provider_prompt,
                    provider_completion_tokens=provider_completion,
                    now=now,
                )
                saved = True
                fresh_user_turns = self.store.daily_turns(user.id, day)
                yield GameEvent(
                    "done",
                    {
                        "narrativa": narrative,
                        "mundo": world,
                        "resumo": summary,
                        "titulo": title,
                        "objetivo": world.get("objetivo"),
                        "objetivoStatus": world.get("objetivoStatus") or "ativa",
                        "objetivoOriginal": world.get("objetivoOriginal"),
                        "modelo": model or route,
                        "rota": route,
                        "tokensEstimados": package.estimated_tokens,
                        "tokensResposta": estimate_tokens(narrative),
                        "cota": {
                            "usados": fresh_user_turns,
                            "limite": limit,
                            "plano": plan,
                        },
                    },
                )
        except GateFull:
            yield GameEvent(
                "erro",
                {"codigo": "ocupado", "mensagem": "O narrador está com muitas mesas agora. Tente de novo em instantes."},
                429,
            )
        except GateTimeout:
            yield GameEvent(
                "erro",
                {"codigo": "ocupado", "mensagem": "A espera pela mesa esgotou. Sua ação não foi gasta. Tente de novo."},
                429,
            )
        finally:
            self._busy.discard(user.id)
            if consumed and not saved:
                self.store.refund_turn(user.id, day)

    def _quota(self, plan: str, used: int, limit: int | None, now: int) -> GameEvent:
        if plan == "paid":
            message = "A cota do plano pago de hoje acabou. Ela volta no próximo reset."
        else:
            message = "Os turnos grátis de hoje acabaram. Assine para continuar agora ou espere o reset."
        return GameEvent(
            "cota",
            {
                "codigo": "cota",
                "mensagem": message,
                "usados": used,
                "limite": limit,
                "plano": plan,
                "resetEm": next_reset_at(now, self.settings.day_offset_hours),
                "assinaturaUrl": self.settings.billing_checkout_url or None,
            },
            402,
        )


def new_saga_world(character: Character, mission: object | None = None) -> dict:
    return initial_world(character, mission)
