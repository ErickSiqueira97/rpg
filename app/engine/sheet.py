"""Ficha 5e: classes leves, PV, PE, migração e subida de nível."""

from __future__ import annotations

from app.engine.math import (
    ATTRIBUTES,
    MEIA_CIRCLE,
    MEIA_PE,
    PACTO_PE,
    PLENA_CIRCLE,
    PLENA_PE,
    level_for_xp,
    modifier,
    proficiency,
    validate_point_buy,
    xp_for_level,
)

# Dado de vida, salvaguardas, reserva, atributo de ataque/PE, perícias iniciais.
CLASSES = {
    "espadachim": {"dv": 10, "salv": ["forca", "vigor"], "reserva": "nenhuma", "atributo": "forca", "pericias": ["atletismo", "intimidacao"], "ataques": (1, 5, 11, 20)},
    "furioso": {"dv": 12, "salv": ["forca", "vigor"], "reserva": "nenhuma", "atributo": "forca", "pericias": ["atletismo", "intimidacao"], "ataques": (1, 5)},
    "punho_de_aura": {"dv": 8, "salv": ["forca", "agilidade"], "reserva": "marcial", "atributo": "agilidade", "pericias": ["acrobacia", "atletismo"], "ataques": (1, 5)},
    "sombra": {"dv": 8, "salv": ["agilidade", "intelecto"], "reserva": "marcial", "atributo": "agilidade", "pericias": ["furtividade", "percepcao"], "ataques": (1,)},
    "cacador": {"dv": 10, "salv": ["forca", "agilidade"], "reserva": "meia", "atributo": "agilidade", "pericias": ["sobrevivencia", "percepcao"], "ataques": (1, 5)},
    "sentinela": {"dv": 10, "salv": ["percepcao", "essencia"], "reserva": "meia", "atributo": "forca", "pericias": ["atletismo", "intuicao"], "ataques": (1, 5)},
    "exorcista": {"dv": 8, "salv": ["percepcao", "essencia"], "reserva": "pacto", "atributo": "essencia", "pericias": ["arcano", "intimidacao"], "ataques": (1,)},
    "grimorista": {"dv": 6, "salv": ["intelecto", "percepcao"], "reserva": "plena", "atributo": "intelecto", "pericias": ["arcano", "historia"], "ataques": (1,)},
    "alquimista": {"dv": 8, "salv": ["intelecto", "vigor"], "reserva": "plena", "atributo": "intelecto", "pericias": ["arcano", "investigacao"], "ataques": (1,)},
    "desperto": {"dv": 6, "salv": ["vigor", "essencia"], "reserva": "plena_nivel", "atributo": "essencia", "pericias": ["arcano", "intuicao"], "ataques": (1,)},
    "invocador": {"dv": 8, "salv": ["intelecto", "percepcao"], "reserva": "plena", "atributo": "percepcao", "pericias": ["natureza", "percepcao"], "ataques": (1,)},
    "devoto": {"dv": 8, "salv": ["percepcao", "essencia"], "reserva": "plena", "atributo": "percepcao", "pericias": ["intuicao", "crencas"], "ataques": (1,)},
    "idolo": {"dv": 8, "salv": ["agilidade", "essencia"], "reserva": "plena", "atributo": "essencia", "pericias": ["persuasao", "atuacao"], "ataques": (1,)},
    "cozinheiro_de_batalha": {"dv": 8, "salv": ["vigor", "percepcao"], "reserva": "marcial", "atributo": "percepcao", "pericias": ["sobrevivencia", "medicina"], "ataques": (1, 5)},
    "artifice": {"dv": 8, "salv": ["vigor", "intelecto"], "reserva": "meia", "atributo": "intelecto", "pericias": ["investigacao", "arcano"], "ataques": (1, 5)},
}

ARCHETYPE_CLASS = {
    "errante": "sombra",
    "espadachim": "espadachim",
    "ocultista": "exorcista",
    "sentinela": "sentinela",
    "artifice": "artifice",
    "artífice": "artifice",
}


def class_id_for(name: str) -> str:
    key = (name or "").strip().lower()
    if key in CLASSES:
        return key
    if key in ARCHETYPE_CLASS:
        return ARCHETYPE_CLASS[key]
    folded = key.replace(" ", "_").replace("-", "_")
    aliases = {
        "punho_de_aura": "punho_de_aura",
        "cozinheiro_de_batalha": "cozinheiro_de_batalha",
        "sangue_de_dragao": "sangue_de_dragao",
    }
    if folded in CLASSES:
        return folded
    return aliases.get(folded, ARCHETYPE_CLASS.get(key, "sombra"))


def hit_die(class_id: str) -> int:
    return CLASSES.get(class_id, CLASSES["sombra"])["dv"]


def hp_at_level_one(class_id: str, vigor: int) -> int:
    return max(1, hit_die(class_id) + modifier(vigor))


def hp_per_level(class_id: str, vigor: int) -> int:
    # Média fixa: metade arredondada para cima + modificador de Vigor. Mínimo 1.
    average = hit_die(class_id) // 2 + 1
    return max(1, average + modifier(vigor))


def extra_attacks(class_id: str, level: int) -> int:
    marks = CLASSES.get(class_id, CLASSES["sombra"])["ataques"]
    return sum(1 for mark in marks if level >= mark)


def pe_max(class_id: str, level: int, attributes: dict[str, int]) -> tuple[int, str]:
    level = max(1, min(20, int(level)))
    spec = CLASSES.get(class_id, CLASSES["sombra"])
    kind = spec["reserva"]
    index = level - 1
    if kind == "plena":
        return PLENA_PE[index], "plena"
    if kind == "plena_nivel":
        return PLENA_PE[index] + level, "plena"
    if kind == "meia":
        return MEIA_PE[index], "meia"
    if kind == "pacto":
        return PACTO_PE[index], "pacto"
    if kind == "marcial":
        attr = spec["atributo"]
        return max(1, level + modifier(attributes.get(attr, 10))), "marcial"
    return 0, "nenhuma"


def circle_max(reserva: str, level: int) -> int:
    index = max(0, min(19, int(level) - 1))
    if reserva == "meia":
        return MEIA_CIRCLE[index]
    if reserva in {"plena", "pacto"}:
        return PLENA_CIRCLE[index] if reserva == "plena" else min(5, PLENA_CIRCLE[index])
    return 0


def blank_sheet(class_id: str, attributes: dict[str, int], *, level: int = 1, xp: int = 0) -> dict:
    spec = CLASSES[class_id]
    pool, reserva = pe_max(class_id, level, attributes)
    hp = hp_at_level_one(class_id, attributes["vigor"])
    for _ in range(2, level + 1):
        hp += hp_per_level(class_id, attributes["vigor"])
    return {
        "escala": "5e",
        "classeId": class_id,
        "racaId": "humano",
        "origemId": "",
        "viaId": "",
        "subclasse": "",
        "traco": "",
        "nivel": level,
        "xp": xp,
        "pendente": False,
        "vidaMax": hp,
        "dadosVidaMax": level,
        "dado": hit_die(class_id),
        "salvaguardas": list(spec["salv"]),
        "pericias": list(spec["pericias"]),
        "especializacao": [],
        "peMax": pool,
        "reserva": reserva,
        "estagio": 0,
        "inspiracao": False,
        "migrada": False,
    }


def migrate_legacy(attributes: dict[str, int], archetype: str) -> tuple[dict[str, int], dict]:
    """Antigo + 4, depois +2 Vigor e +1 Força, teto 20. PV pela classe nova."""
    updated = {}
    for name in ATTRIBUTES:
        updated[name] = min(20, int(attributes[name]) + 4)
    updated["vigor"] = min(20, updated["vigor"] + 2)
    updated["forca"] = min(20, updated["forca"] + 1)
    class_id = class_id_for(archetype)
    sheet = blank_sheet(class_id, updated)
    sheet["migrada"] = True
    return updated, sheet


def apply_origin_bonus(base: dict[str, int], bonus: dict[str, int]) -> dict[str, int]:
    cleaned = validate_point_buy(base)
    if not isinstance(bonus, dict) or not bonus:
        raise ValueError("A origem soma +2 e +1, ou +1 em três atributos.")
    values = {name: int(bonus[name]) for name in bonus}
    if any(name not in ATTRIBUTES for name in values) or any(amount not in {1, 2} for amount in values.values()):
        raise ValueError("O bônus da origem é +2 e +1, ou +1 em três atributos.")
    amounts = sorted(values.values(), reverse=True)
    if amounts not in ([2, 1], [1, 1, 1]):
        raise ValueError("O bônus da origem é +2 e +1, ou +1 em três atributos.")
    final = dict(cleaned)
    for name, amount in values.items():
        final[name] = min(20, final[name] + amount)
    return final


def grant_xp(sheet: dict, amount: int, vigor: int) -> dict:
    updated = dict(sheet)
    updated["xp"] = int(updated.get("xp") or 0) + max(0, int(amount))
    level = int(updated.get("nivel") or 1)
    target = level_for_xp(updated["xp"])
    while level < target and level < 20:
        level += 1
        updated["vidaMax"] = int(updated.get("vidaMax") or 1) + hp_per_level(updated["classeId"], vigor)
        updated["dadosVidaMax"] = level
        if level in {4, 8, 12, 16, 19}:
            updated["pendente"] = True
    updated["nivel"] = level
    return updated


def recompute_pe(sheet: dict, attributes: dict[str, int]) -> dict:
    updated = dict(sheet)
    pool, reserva = pe_max(updated["classeId"], int(updated.get("nivel") or 1), attributes)
    updated["peMax"] = pool
    updated["reserva"] = reserva
    updated.pop("_pool_hint", None)
    return updated


def apply_asi(attributes: dict[str, int], sheet: dict, choice: dict) -> tuple[dict[str, int], dict]:
    if not sheet.get("pendente"):
        raise ValueError("Não há melhoria de atributo pendente.")
    updated = dict(attributes)
    mode = choice.get("modo") or "um"
    if mode == "um":
        name = choice.get("atributo")
        if name not in ATTRIBUTES:
            raise ValueError("Escolha um atributo.")
        updated[name] = min(20, int(updated[name]) + 2)
    elif mode == "dois":
        names = choice.get("atributos") or []
        if len(names) != 2 or len(set(names)) != 2 or any(name not in ATTRIBUTES for name in names):
            raise ValueError("Escolha dois atributos diferentes.")
        for name in names:
            updated[name] = min(20, int(updated[name]) + 1)
    else:
        raise ValueError("Modo de melhoria desconhecido.")
    new_sheet = dict(sheet)
    new_sheet["pendente"] = False
    new_sheet = recompute_pe(new_sheet, updated)
    return updated, new_sheet


def training_xp_cap(level: int) -> int:
    """10% do XP necessário para sair do nível atual (do patamar até o próximo)."""
    if level >= 20:
        return 0
    span = xp_for_level(level + 1) - xp_for_level(level)
    return max(1, span // 10)


def proficiency_bonus(sheet: dict) -> int:
    return proficiency(int(sheet.get("nivel") or 1))
