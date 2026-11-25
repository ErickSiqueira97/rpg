import asyncio

import pytest

from app.gate import Gate, GateFull, GateTimeout


@pytest.mark.asyncio
async def test_fila_curta_recusa_quando_nao_cabe():
    gate = Gate(limit=1, max_waiting=1, wait_seconds=0.2)
    release = asyncio.Event()
    started = asyncio.Event()

    async def hold():
        async with gate:
            started.set()
            await release.wait()

    first = asyncio.create_task(hold())
    await started.wait()
    waiting = asyncio.create_task(hold())
    await asyncio.sleep(0.02)
    with pytest.raises(GateFull):
        async with gate:
            pass
    release.set()
    await first
    await waiting


@pytest.mark.asyncio
async def test_espera_demais_nao_segura_a_vaga():
    gate = Gate(limit=1, max_waiting=2, wait_seconds=0.05)
    release = asyncio.Event()

    async def hold():
        async with gate:
            await release.wait()

    blocker = asyncio.create_task(hold())
    await asyncio.sleep(0.01)
    with pytest.raises(GateTimeout):
        async with gate:
            pass
    release.set()
    await blocker
    async with gate:
        assert gate._active == 1
