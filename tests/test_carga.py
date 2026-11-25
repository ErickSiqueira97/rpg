import pytest

from app.carga import simular


@pytest.mark.asyncio
async def test_cem_jogadores_simultaneos(tmp_path):
    result = await simular(100, database_path=str(tmp_path / "carga.sqlite"))
    assert result.ok == 100
    assert result.falhas == 0
    assert result.p95_ms < 30_000
