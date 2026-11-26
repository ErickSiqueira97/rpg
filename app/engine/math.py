"""Números fechados: modificador, compra de pontos, proficiência, CD e tetos."""

from __future__ import annotations

ATTRIBUTES = ("forca", "agilidade", "vigor", "percepcao", "intelecto", "essencia")

POINT_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUDGET = 27

XP_BY_LEVEL = (
    0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
    85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000,
)

DC_LABELS = {
    "muito_facil": 5,
    "facil": 10,
    "medio": 15,
    "dificil": 20,
    "muito_dificil": 25,
    "quase_impossivel": 30,
}

SKILLS = {
    "acrobacia": "agilidade",
    "adestrar_animais": "percepcao",
    "arcano": "intelecto",
    "atletismo": "forca",
    "atuacao": "essencia",
    "crencas": "intelecto",
    "enganacao": "essencia",
    "furtividade": "agilidade",
    "historia": "intelecto",
    "intimidacao": "essencia",
    "intuicao": "percepcao",
    "investigacao": "intelecto",
    "medicina": "percepcao",
    "natureza": "intelecto",
    "percepcao": "percepcao",
    "persuasao": "essencia",
    "prestidigitacao": "agilidade",
    "sobrevivencia": "percepcao",
}

SKILL_NAMES = {
    "acrobacia": "Acrobacia",
    "adestrar_animais": "Adestrar Animais",
    "arcano": "Arcano",
    "atletismo": "Atletismo",
    "atuacao": "Atuação",
    "crencas": "Crenças",
    "enganacao": "Enganação",
    "furtividade": "Furtividade",
    "historia": "História",
    "intimidacao": "Intimidação",
    "intuicao": "Intuição",
    "investigacao": "Investigação",
    "medicina": "Medicina",
    "natureza": "Natureza",
    "percepcao": "Percepção",
    "persuasao": "Persuasão",
    "prestidigitacao": "Prestidigitação",
    "sobrevivencia": "Sobrevivência",
}

ATTR_NAMES = {
    "forca": "Força",
    "agilidade": "Agilidade",
    "vigor": "Vigor",
    "percepcao": "Percepção",
    "intelecto": "Intelecto",
    "essencia": "Essência",
}

CONDITIONS = (
    "agarrado", "amedrontado", "atordoado", "caido", "cego", "contido",
    "enfeiticado", "envenenado", "exaustao", "inconsciente", "incapacitado",
    "invisivel", "paralisado", "petrificado", "surdo",
)

# Espaços do SRD convertidos em PE. A coluna marcial da tabela é só exemplo.
PLENA_PE = (4, 6, 14, 17, 27, 32, 38, 44, 57, 64, 64, 64, 64, 64, 64, 64, 64, 71, 71, 71)
MEIA_PE = (4, 4, 6, 6, 14, 14, 17, 17, 27, 27, 32, 32, 38, 38, 44, 44, 57, 57, 64, 64)
PACTO_PE = (2, 4, 6, 6, 10, 10, 12, 12, 14, 14, 21, 21, 21, 21, 21, 21, 28, 28, 28, 28)
PLENA_CIRCLE = (1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5)
MEIA_CIRCLE = (1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5)


def modifier(value: int) -> int:
    return (int(value) - 10) // 2


def proficiency(level: int) -> int:
    level = max(1, min(20, int(level)))
    return 2 + (level - 1) // 4


def level_for_xp(xp: int) -> int:
    level = 1
    for index, need in enumerate(XP_BY_LEVEL, start=1):
        if xp >= need:
            level = index
    return level


def xp_for_level(level: int) -> int:
    level = max(1, min(20, int(level)))
    return XP_BY_LEVEL[level - 1]


def point_buy_cost(values: dict[str, int]) -> int:
    total = 0
    for name in ATTRIBUTES:
        value = int(values[name])
        if value not in POINT_COST:
            raise ValueError(f"{name} na compra fica entre 8 e 15.")
        total += POINT_COST[value]
    return total


def validate_point_buy(values: dict[str, int]) -> dict[str, int]:
    cleaned = {name: int(values[name]) for name in ATTRIBUTES}
    spent = point_buy_cost(cleaned)
    if spent != POINT_BUDGET:
        raise ValueError(f"A compra de pontos usa {POINT_BUDGET} pontos (você usou {spent}).")
    return cleaned


def dc_from_label(label: str, *, mode: str, profile: str) -> int:
    raw = DC_LABELS.get(str(label or "medio"), 15)
    if mode == "saga":
        cap = {"facil": 20, "normal": 25, "brutal": 30}.get(profile, 25)
    else:
        cap = 20
    return max(5, min(cap, raw))


def attack_bonus_cap(level: int) -> int:
    if level <= 4:
        return 7
    if level <= 10:
        return 10
    if level <= 16:
        return 12
    return 14


def armor_class_cap(level: int) -> int:
    if level <= 4:
        return 20
    if level <= 10:
        return 21
    if level <= 16:
        return 22
    return 23


def technique_dc_cap(level: int) -> int:
    if level <= 4:
        return 15
    if level <= 10:
        return 17
    if level <= 16:
        return 19
    return 21


def pe_per_turn_cap(level: int) -> int:
    if level <= 4:
        return 5
    if level <= 10:
        return 9
    return 10


def temp_hp_cap(level: int, grade: str) -> int:
    mult = {"menor": 2, "maior": 4, "suprema": 6}.get(grade, 2)
    return mult * max(1, int(level))


def clamp(value: int, limit: int) -> tuple[int, bool]:
    if value > limit:
        return limit, True
    return value, False
