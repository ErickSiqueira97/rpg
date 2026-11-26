"""Uso: python scripts/carga.py [jogadores]

O narrador é falso. O script mede se o servidor aguenta muitos jogadores
ao mesmo tempo (cadastro, ficha, saga, dois turnos, leitura da memória).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.carga import simular


def main() -> None:
    jogadores = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    result = asyncio.run(simular(jogadores))
    print(
        f"ok={result.ok}/{result.jogadores} falhas={result.falhas} "
        f"p50={result.p50_ms:.0f}ms p95={result.p95_ms:.0f}ms max={result.max_ms:.0f}ms"
    )


if __name__ == "__main__":
    main()
