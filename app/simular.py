"""Simulador de equilíbrio. Só o motor, sem narrador.

Uso: python -m app.simular --lutas 200
"""

from __future__ import annotations

import argparse
import json

from app.catalog import RACES
from app.engine.duel import fight, make_profile
from app.engine.sheet import CLASSES


def combo_key(race: str, class_id: str, level: int) -> str:
    return f"{race}|{class_id}|{level}"


def simulate(fights_each: int = 100, seed: int = 1, levels: tuple[int, ...] = (1, 5, 11, 17)) -> list[dict]:
    attrs = {"forca": 16, "agilidade": 14, "vigor": 14, "percepcao": 12, "intelecto": 12, "essencia": 10}
    rows = []
    for race in RACES:
        for class_id in CLASSES:
            for level in levels:
                wins = 0
                for index in range(fights_each):
                    left = make_profile(class_id, attrs, level, nome=race["id"], race_id=race["id"])
                    right = make_profile(class_id, attrs, level, nome="espelho", race_id=race["id"])
                    result = fight(left, right, f"{seed}|{race['id']}|{class_id}|{level}|{index}")
                    if result["vencedor"] == "jogador":
                        wins += 1
                rate = round(100 * wins / fights_each) if fights_each else 0
                rows.append(
                    {
                        "raca": race["id"],
                        "classe": class_id,
                        "nivel": level,
                        "lutas": fights_each,
                        "vitorias": wins,
                        "taxa": rate,
                        "fora": rate < 40 or rate > 60,
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula lutas espelho sem narrador.")
    parser.add_argument("--lutas", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rows = simulate(args.lutas, args.seed)
    flagged = [row for row in rows if row["fora"]]
    print(json.dumps({"combinacoes": len(rows), "fora_da_faixa": len(flagged), "amostra": rows[:8], "flags": flagged[:20]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
