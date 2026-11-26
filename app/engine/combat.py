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


def weapon_profile(class_id: str, sheet: dict, attributes: dict, zone: str = "corpo") -> tuple[int, str, bool, str]:
    """Dado da arma/golpe, tipo de dano, se é à distância e atributo principal."""
    from app.engine.math import modifier

    level = max(1, min(20, int(sheet.get("nivel") or 1)))
    agi_mod = modifier(attributes.get("agilidade", 10))
    for_mod = modifier(attributes.get("forca", 10))
    finesse = "agilidade" if agi_mod > for_mod else "forca"

    if class_id == "punho_de_aura":
        sides = 6 if level < 5 else (8 if level < 11 else (10 if level < 17 else 12))
        return sides, "contundente", False, finesse
    if class_id == "furioso":
        return 12, "cortante", False, "forca"
    if class_id == "espadachim":
        return 10, "cortante", False, finesse
    if class_id == "sentinela":
        return 8, "cortante", False, "forca"
    if class_id == "cacador":
        ranged = zone != "corpo"
        return 8, "perfurante", ranged, "agilidade" if ranged else finesse
    if class_id == "artifice":
        return 10, "perfurante", True, "agilidade"
    if class_id == "sombra":
        return 6, "perfurante", False, "agilidade"
    if class_id == "cozinheiro_de_batalha":
        return 6, "contundente", False, finesse
    return 6, "contundente", False, finesse
