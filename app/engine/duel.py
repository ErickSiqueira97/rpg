"""Luta só com o motor: Professor, arena e simulador. Sem narrador."""

from __future__ import annotations

from app.engine.math import attack_bonus_cap, clamp, modifier, proficiency
from app.engine.rng import roller
from app.engine.sheet import CLASSES, extra_attacks, hp_at_level_one, hp_per_level

ARCHETYPES = {
    "tanque": {"classe": "sentinela", "forca": 16, "agilidade": 10, "vigor": 16, "ca_extra": 2},
    "dano": {"classe": "espadachim", "forca": 16, "agilidade": 14, "vigor": 14, "ca_extra": 0},
    "controle": {"classe": "grimorista", "forca": 8, "agilidade": 14, "vigor": 14, "ca_extra": 0},
    "conjurador": {"classe": "exorcista", "forca": 8, "agilidade": 14, "vigor": 14, "ca_extra": 0},
    "transformador": {"classe": "furioso", "forca": 16, "agilidade": 12, "vigor": 16, "ca_extra": 0},
}


def _hp(class_id: str, vigor: int, level: int) -> int:
    total = hp_at_level_one(class_id, vigor)
    for _ in range(2, level + 1):
        total += hp_per_level(class_id, vigor)
    return total


def make_profile(class_id: str, attrs: dict, level: int, *, ca_extra: int = 0, nome: str = "") -> dict:
    level = max(1, min(20, int(level)))
    spec = CLASSES.get(class_id, CLASSES["espadachim"])
    ability = attrs.get(spec["atributo"], 10)
    bonus, _cut = clamp(modifier(ability) + proficiency(level), attack_bonus_cap(level))
    die = 8 if spec["dv"] >= 8 else 6
    ac = min(10 + modifier(attrs.get("agilidade", 10)) + 3 + ca_extra, 10 + modifier(attrs.get("agilidade", 10)) + 6)
    return {
        "nome": nome or class_id,
        "classe": class_id,
        "nivel": level,
        "vida": _hp(class_id, attrs.get("vigor", 10), level),
        "vidaMax": _hp(class_id, attrs.get("vigor", 10), level),
        "ca": ac,
        "ataque": bonus,
        "dado": die,
        "mod": modifier(ability),
        "ataques": extra_attacks(class_id, level),
        "defesa": False,
    }


def profile_from_character(character, level: int | None = None) -> dict:
    sheet = character.sheet or {}
    class_id = sheet.get("classeId") or "espadachim"
    chosen = int(level or sheet.get("nivel") or 1)
    return make_profile(class_id, character.attributes, chosen, nome=character.name)


def archetype_profile(kind: str, level: int) -> dict:
    data = ARCHETYPES[kind]
    attrs = {
        "forca": data["forca"], "agilidade": data["agilidade"], "vigor": data["vigor"],
        "percepcao": 12, "intelecto": 12, "essencia": 12,
    }
    return make_profile(data["classe"], attrs, level, ca_extra=data["ca_extra"], nome=kind)


def _strike(rng, attacker, defender, half_damage: bool) -> tuple[int, str]:
    ac = defender["ca"] + (2 if defender.get("defesa") else 0)
    roll = rng.randint(1, 20)
    if roll == 1 or (roll != 20 and roll + attacker["ataque"] < ac):
        return 0, f"⚔️ {attacker['nome']}: {roll} + {attacker['ataque']} vs CA {ac} — erro"
    sides = attacker["dado"]
    dice = [rng.randint(1, sides)]
    if roll == 20:
        dice.append(rng.randint(1, sides))
    damage = max(1, sum(dice) + attacker["mod"])
    if half_damage:
        damage = max(1, damage // 2)
    defender["vida"] -= damage
    kind = "crítico" if roll == 20 else "acerto"
    return damage, f"⚔️ {attacker['nome']}: {roll} + {attacker['ataque']} vs CA {ac} — {kind} · {damage}"


def fight(left: dict, right: dict, seed: str, difficulty: str = "padrao") -> dict:
    rng = roller(seed)
    left = dict(left)
    right = dict(right)
    half = difficulty == "aprendiz"
    if half:
        right["ca"] = max(10, right["ca"] - 2)
    lines = []
    init_left = rng.randint(1, 20)
    init_right = rng.randint(1, 20)
    order = ((left, right), (right, left)) if init_left >= init_right else ((right, left), (left, right))
    lines.append(f"Iniciativa {init_left} a {init_right}.")
    rounds = 0
    while left["vida"] > 0 and right["vida"] > 0 and rounds < 40:
        rounds += 1
        for attacker, defender in order:
            if attacker["vida"] <= 0 or defender["vida"] <= 0:
                break
            attacker["defesa"] = attacker["vida"] * 2 <= attacker["vidaMax"]
            swings = 0 if attacker["defesa"] else min(5, attacker["ataques"])
            if swings == 0:
                lines.append(f"{attacker['nome']} defende.")
                continue
            for _ in range(swings):
                _damage, line = _strike(rng, attacker, defender, half and attacker is right)
                lines.append(line)
                if defender["vida"] <= 0:
                    break
        left["defesa"] = False
        right["defesa"] = False
    winner = "jogador" if right["vida"] <= 0 and left["vida"] > 0 else "oponente" if left["vida"] <= 0 else "empate"
    lines.append(f"Fim em {rounds} rodadas. Vida {max(0, left['vida'])}/{left['vidaMax']}.")
    return {"vencedor": winner, "rodadas": rounds, "linhas": lines, "vida": max(0, left["vida"])}
