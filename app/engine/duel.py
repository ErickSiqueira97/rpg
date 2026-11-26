"""Luta só com o motor: Professor, arena e simulador. Sem narrador."""

from __future__ import annotations

from app.engine.combat import weapon_profile
from app.engine.math import armor_class_cap, attack_bonus_cap, clamp, modifier, proficiency
from app.engine.rng import roller
from app.engine.sheet import CLASSES, armor_class, extra_attacks, hp_at_level_one, hp_per_level

ARCHETYPES = {
    "tanque": {"classe": "sentinela", "forca": 16, "agilidade": 10, "vigor": 16, "ca_extra": 2},
    "dano": {"classe": "espadachim", "forca": 16, "agilidade": 14, "vigor": 14, "ca_extra": 0},
    "controle": {"classe": "grimorista", "forca": 8, "agilidade": 14, "vigor": 14, "ca_extra": 0},
    "conjurador": {"classe": "exorcista", "forca": 8, "agilidade": 14, "vigor": 14, "ca_extra": 0},
    "transformador": {"classe": "furioso", "forca": 16, "agilidade": 12, "vigor": 16, "ca_extra": 0},
}


def _hp(class_id: str, vigor: int, level: int, race_id: str = "humano") -> int:
    total = hp_at_level_one(class_id, vigor, race_id)
    for _ in range(2, level + 1):
        total += hp_per_level(class_id, vigor, race_id)
    return total


def make_profile(
    class_id: str,
    attrs: dict,
    level: int,
    *,
    ca_extra: int = 0,
    nome: str = "",
    race_id: str = "humano",
    subclasse: str = "",
    traco: str = "",
    estagio: int = 0,
) -> dict:
    level = max(1, min(20, int(level)))
    spec = CLASSES.get(class_id, CLASSES["espadachim"])
    sides, _dmg_type, _ranged, weapon_attr = weapon_profile(
        class_id, {"nivel": level, "racaId": race_id, "estagio": estagio}, attrs
    )
    if race_id == "feral":
        sides = max(sides, 8 if (estagio >= 1 or level >= 5) else 6)
    ability = attrs.get(spec["atributo"], attrs.get(weapon_attr, 10))
    bonus, _cut = clamp(modifier(ability) + proficiency(level), attack_bonus_cap(level))
    sheet = {"classeId": class_id, "racaId": race_id, "nivel": level, "traco": traco, "estagio": estagio}
    ac = min(armor_class_cap(level), armor_class(attrs, sheet) + ca_extra)
    hp = _hp(class_id, attrs.get("vigor", 10), level, race_id)
    return {
        "nome": nome or class_id,
        "classe": class_id,
        "subclasse": subclasse,
        "criticoAmpliado": (
            class_id == "espadachim"
            and subclasse.strip().casefold() == "lâmina campeã".casefold()
            and level >= 3
        ),
        "raca": race_id,
        "traco": traco,
        "estagio": estagio,
        "nivel": level,
        "vida": hp,
        "vidaMax": hp,
        "ca": ac,
        "ataque": bonus,
        "iniciativa": modifier(attrs.get("agilidade", 10)),
        "dado": sides,
        "mod": modifier(ability),
        "ataques": extra_attacks(class_id, level),
        "defesa": False,
        "cai1Usado": False,
    }


def profile_from_character(character, level: int | None = None) -> dict:
    sheet = character.sheet or {}
    class_id = sheet.get("classeId") or "espadachim"
    chosen = int(level or sheet.get("nivel") or 1)
    return make_profile(
        class_id,
        character.attributes,
        chosen,
        nome=character.name,
        race_id=sheet.get("racaId") or "humano",
        subclasse=sheet.get("subclasse") or "",
        traco=sheet.get("traco") or "",
        estagio=int(sheet.get("estagio") or 0),
    )


def archetype_profile(kind: str, level: int) -> dict:
    data = ARCHETYPES[kind]
    attrs = {
        "forca": data["forca"], "agilidade": data["agilidade"], "vigor": data["vigor"],
        "percepcao": 12, "intelecto": 12, "essencia": 12,
    }
    return make_profile(data["classe"], attrs, level, ca_extra=data["ca_extra"], nome=kind)


def _should_defend(
    fighter: dict,
    round_number: int,
    last_defense_round: int | None,
) -> bool:
    hp = max(0, int(fighter["vida"]))
    max_hp = max(1, int(fighter["vidaMax"]))
    if hp * 4 >= max_hp:
        return False
    if last_defense_round is not None and round_number - last_defense_round < 2:
        return False
    return True


def _strike(rng, attacker, defender, half_damage: bool) -> tuple[int, str]:
    ac = defender["ca"] + (2 if defender.get("defesa") else 0)
    previous_hp = max(0, defender["vida"])
    rolls = [rng.randint(1, 20)]
    if rolls[0] == 1 and attacker.get("raca") == "pequenino":
        rolls.append(rng.randint(1, 20))
    roll = rolls[-1]
    attack_roll = " / ".join(f"🎲 {value}" for value in rolls)
    attack_total = roll + attacker["ataque"]
    crit_min = 19 if attacker.get("criticoAmpliado") else 20
    crit = roll >= crit_min
    if roll == 1 or (not crit and roll + attacker["ataque"] < ac):
        hp = max(0, defender["vida"])
        return 0, f"⚔️ {attacker['nome']}: {attack_roll} + {attacker['ataque']} = {attack_total} vs CA {ac} — erro · {defender['nome']} {previous_hp} → {hp} PV"
    sides = attacker["dado"]
    dice = [rng.randint(1, sides)]
    if crit:
        dice.append(rng.randint(1, sides))
    rolled_damage = sum(dice) + attacker["mod"]
    damage_before_half = max(1, rolled_damage)
    damage = damage_before_half
    if half_damage:
        damage = max(1, damage // 2)
    defender["vida"] -= damage
    if defender["vida"] <= 0 and not defender.get("cai1Usado"):
        if defender.get("raca") == "oni" or defender.get("traco") == "divida_com_fera":
            defender["cai1Usado"] = True
            defender["vida"] = 1
    kind = "crítico" if crit else "acerto"
    hp = max(0, defender["vida"])
    damage_expression = f"{len(dice)}d{sides}"
    if attacker["mod"]:
        damage_expression += f"{attacker['mod']:+d}"
    damage_roll = f"🎲 dano {damage_expression} = {rolled_damage}"
    if rolled_damage < 1:
        damage_roll += " (mínimo 1)"
    if half_damage:
        damage_roll += f" · metade: {damage}"
    return damage, f"⚔️ {attacker['nome']}: {attack_roll} + {attacker['ataque']} = {attack_total} vs CA {ac} — {kind} · {damage_roll} · {defender['nome']} {previous_hp} → {hp} PV"


def fight(left: dict, right: dict, seed: str, difficulty: str = "padrao") -> dict:
    rng = roller(seed)
    left = dict(left)
    right = dict(right)
    half = difficulty == "aprendiz"
    if half:
        right["ca"] = max(10, right["ca"] - 2)
    lines = []
    init_left_roll = rng.randint(1, 20)
    init_right_roll = rng.randint(1, 20)
    init_left = init_left_roll + left["iniciativa"]
    init_right = init_right_roll + right["iniciativa"]
    order = ((left, right), (right, left)) if init_left >= init_right else ((right, left), (left, right))
    lines.append(
        f"Iniciativa {left['nome']}: 🎲 {init_left_roll} + {left['iniciativa']} = {init_left}; "
        f"{right['nome']}: 🎲 {init_right_roll} + {right['iniciativa']} = {init_right}."
    )
    rounds = 0
    last_defense_round = {id(left): None, id(right): None}
    while left["vida"] > 0 and right["vida"] > 0 and rounds < 40:
        rounds += 1
        lines.extend(["", f"── Rodada {rounds} ──"])
        for attacker, defender in order:
            if attacker["vida"] <= 0 or defender["vida"] <= 0:
                break
            attacker["defesa"] = False
            last_defended = last_defense_round[id(attacker)]
            if _should_defend(attacker, rounds, last_defended):
                attacker["defesa"] = True
                last_defense_round[id(attacker)] = rounds
                lines.append(f"{attacker['nome']} defende: +2 CA contra ataques até seu próximo turno.")
                continue
            swings = min(5, attacker["ataques"])
            for _ in range(swings):
                _damage, line = _strike(rng, attacker, defender, half and attacker is right)
                lines.append(line)
                if defender["vida"] <= 0:
                    break
    winner = "jogador" if right["vida"] <= 0 and left["vida"] > 0 else "oponente" if left["vida"] <= 0 else "empate"
    outcome = {"jogador": "Vitória", "oponente": "Derrota", "empate": "Empate"}[winner]
    lines.append(
        f"PV finais — {left['nome']}: {max(0, left['vida'])}/{left['vidaMax']}; "
        f"{right['nome']}: {max(0, right['vida'])}/{right['vidaMax']}."
    )
    return {
        "vencedor": winner,
        "rodadas": rounds,
        "resultado": f"{outcome} em {rounds} rodadas.",
        "linhas": lines,
        "vida": max(0, left["vida"]),
    }
