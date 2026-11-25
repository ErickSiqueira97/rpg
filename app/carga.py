"""Simula vários jogadores ao mesmo tempo, com o narrador falso (sem rede)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.factory import create_app

SHEET = {
    "nome": "Lia",
    "origem": "Porto de Véspera",
    "arquetipo": "Errante",
    "conceito": "procura um farol",
    "atributos": {
        "forca": 6,
        "agilidade": 6,
        "vigor": 6,
        "percepcao": 6,
        "intelecto": 6,
        "essencia": 6,
    },
}


@dataclass
class CargaResult:
    jogadores: int
    ok: int
    falhas: int
    p50_ms: float
    p95_ms: float
    max_ms: float


async def simular(jogadores: int = 100, database_path: str = ":memory:") -> CargaResult:
    settings = Settings(
        database_path=database_path,
        fake=True,
        free_turns_per_day=50,
        trial_turns_per_day=50,
        max_concurrent=20,
        max_waiting=max(80, jogadores),
        queue_wait_seconds=15,
        moderation="off",
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    latencies: list[float] = []
    failures: list[str] = []

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        async def jogador(index: int) -> None:
            started = time.perf_counter()
            try:
                created = await client.post(
                    "/api/cadastro",
                    json={"usuario": f"jog{index}", "senha": "segredo"},
                )
                if created.status_code != 200:
                    failures.append(f"cadastro {index}: {created.status_code} {created.text}")
                    return
                token = created.json()["token"]
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
                sheet = dict(SHEET)
                sheet["nome"] = f"Lia {index}"
                character = await client.post("/api/personagens", headers=headers, json=sheet)
                if character.status_code != 200:
                    failures.append(f"ficha {index}: {character.status_code} {character.text}")
                    return
                saga = await client.post(
                    "/api/sagas",
                    headers=headers,
                    json={"personagemId": character.json()["id"]},
                )
                if saga.status_code != 200:
                    failures.append(f"saga {index}: {saga.status_code} {saga.text}")
                    return
                saga_id = saga.json()["id"]
                opening = await client.post(
                    f"/api/sagas/{saga_id}/turnos",
                    headers=headers,
                    json={"abertura": True},
                )
                if opening.status_code != 200 or "narrativa" not in opening.json():
                    failures.append(f"abertura {index}: {opening.status_code} {opening.text}")
                    return
                action = await client.post(
                    f"/api/sagas/{saga_id}/turnos",
                    headers=headers,
                    json={"texto": "Observo a névoa e espero."},
                )
                if action.status_code != 200 or "narrativa" not in action.json():
                    failures.append(f"acao {index}: {action.status_code} {action.text}")
                    return
                resumed = await client.get(f"/api/sagas/{saga_id}", headers=headers)
                messages = resumed.json().get("mensagens", []) if resumed.status_code == 200 else []
                if len(messages) < 3 or not resumed.json().get("resumo"):
                    failures.append(f"memoria {index}: historico incompleto")
                    return
                latencies.append((time.perf_counter() - started) * 1000)
            except Exception as exc:  # um jogador falho não esconde o relatório
                failures.append(f"excecao {index}: {exc}")

        await asyncio.gather(*(jogador(index) for index in range(jogadores)))

    app.state.store.close()
    latencies.sort()
    count = len(latencies)

    def percentile(rank: float) -> float:
        if not latencies:
            return 0
        index = min(len(latencies) - 1, max(0, int(round((len(latencies) - 1) * rank))))
        return latencies[index]

    if failures:
        detail = "\n".join(failures[:8])
        raise RuntimeError(f"{len(failures)} jogadores falharam:\n{detail}")
    return CargaResult(
        jogadores=jogadores,
        ok=count,
        falhas=len(failures),
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        max_ms=latencies[-1] if latencies else 0,
    )
