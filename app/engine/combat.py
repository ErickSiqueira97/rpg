"""Combate por zonas. No máximo cinco ataques no turno, fora o Surto do Espadachim."""

from __future__ import annotations

ZONES = ("corpo", "perto", "longe")
COVER = {"": 0, "meia": 2, "tres_quartos": 5, "total": None}

DAMAGE = (
    "acido", "contundente", "frio", "fogo", "energia", "eletrico", "necrotico",
    "perfurante", "veneno", "psiquico", "radiante", "cortante", "trovao",
)


def cover_bonus(kind: str) -> int | None:
    return COVER.get(kind, 0)


def apply_resistance(amount: int, damage_type: str, profile: dict) -> int:
    immunities = set(profile.get("imunidades") or [])
    resistances = set(profile.get("resistencias") or [])
    vulnerabilities = set(profile.get("vulnerabilidades") or [])
    if damage_type in immunities:
        return 0
    if damage_type in resistances and damage_type in vulnerabilities:
        return amount
    if damage_type in resistances:
        return amount // 2
    if damage_type in vulnerabilities:
        return amount * 2
    return amount


def ranged_disadvantage(zone: str, ranged: bool) -> bool:
    return bool(ranged) and zone == "corpo"


def opportunity(before: str, after: str, disengage: bool) -> bool:
    return before == "corpo" and after != "corpo" and not disengage


def attack_count(base: int, bonus_action: int = 0, surge: bool = False) -> int:
    total = base + bonus_action
    if surge:
        return total + base
    return min(5, total)


def initiative(modifier_value: int, surprised: bool, rng) -> int:
    first = rng.randint(1, 20)
    if not surprised:
        return first + modifier_value
    second = rng.randint(1, 20)
    return min(first, second) + modifier_value


def passive_perception(modifier_value: int, proficient: bool, prof: int) -> int:
    return 10 + modifier_value + (prof if proficient else 0)
