"""Gerador determinístico. A mesma chave de turno devolve os mesmos dados."""

from __future__ import annotations

import hashlib
import random


def turn_key(saga_id: str, message_count: int, action: str) -> str:
    blob = f"{saga_id}|{message_count}|{action}".encode()
    return hashlib.sha256(blob).hexdigest()


def roller(seed: str):
    digest = hashlib.sha256(seed.encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def roll_die(rng: random.Random, sides: int) -> int:
    return rng.randint(1, sides)


def roll_d20(rng: random.Random, advantage: bool, disadvantage: bool) -> tuple[list[int], int, str]:
    if advantage and disadvantage:
        advantage = False
        disadvantage = False
    if advantage or disadvantage:
        dice = [rng.randint(1, 20), rng.randint(1, 20)]
        used = max(dice) if advantage else min(dice)
        return dice, used, "vantagem" if advantage else "desvantagem"
    rolled = rng.randint(1, 20)
    return [rolled], rolled, "normal"
