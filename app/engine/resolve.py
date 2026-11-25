"""Resolve um pedido da IA. Números, sucesso, PV, itens, XP e morte saem daqui."""

from __future__ import annotations

import json
import re
import unicodedata

from app.engine.math import (
    ATTR_NAMES,
    CONDITIONS,
    SKILL_NAMES,
    SKILLS,
    armor_class_cap,
    attack_bonus_cap,
    clamp,
    dc_from_label,
    modifier,
    pe_per_turn_cap,
    technique_dc_cap,
)
from app.engine.rng import roll_d20, roll_die, roller
from app.engine.sheet import extra_attacks, hp_at_level_one, proficiency_bonus

RISK_DICE = {
    "dano_leve": (1, 4, 4),
    "dano_medio": (1, 6, 3),
    "dano_grave": (1, 8, 2),
}

SOCIAL = {"persuasao", "enganacao", "intimidacao", "atuacao"}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def parse_intent(raw: str) -> dict:
    start = raw.find("{")
    end = raw.rfind("}")
    data = {}
    if start >= 0 and end > start:
        try:
            loaded = json.loads(raw[start : end + 1])
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    teste = data.get("teste") if isinstance(data.get("teste"), dict) else {}
    riscos = data.get("riscos") if isinstance(data.get("riscos"), dict) else {}
    vantagem = str(teste.get("vantagem") or "nenhuma")
    if vantagem not in {"vantagem", "desvantagem", "nenhuma"}:
        vantagem = "nenhuma"
    tipo = str(teste.get("tipo") or "nenhum")
    if tipo not in {"pericia", "atributo", "salvaguarda", "ataque", "nenhum"}:
        tipo = "nenhum"
    pericia = str(teste.get("pericia") or "")
    if pericia not in SKILLS:
        pericia = ""
    atributo = str(teste.get("atributo") or "")
    if atributo not in ATTR_NAMES:
        atributo = SKILLS.get(pericia, "")
    condicao = str(riscos.get("condicao_na_falha") or "")
    if condicao not in CONDITIONS or condicao == "exaustao":
        condicao = ""
    falha = str(riscos.get("falha") or "nenhum")
    if falha not in RISK_DICE and falha != "nenhum":
        falha = "nenhum"
    return {
        "intencao": str(data.get("intencao") or "nenhum"),
        "tipo": tipo,
        "atributo": atributo,
        "pericia": pericia,
        "dificuldade": str(teste.get("dificuldade") or "medio"),
        "vantagem": vantagem,
        "condicao": condicao,
        "falha": falha,
        "forcado": False,
    }


def _force_risky(action: str, intent: dict) -> dict:
    if intent.get("tipo") not in {"nenhum", "", None}:
        return intent
    text = _fold(action)
    forced = dict(intent)
    if re.search(r"\b(ataco|ataque|atacar|golpe|corto|soco|espada|flecha|disparo)\b", text):
        forced.update({"tipo": "ataque", "intencao": "atacar", "atributo": "forca", "forcado": True})
    elif re.search(r"\b(escond|furtiv|sorrateir)\b", text):
        forced.update({"tipo": "pericia", "pericia": "furtividade", "atributo": "agilidade", "dificuldade": "medio", "intencao": "esconder", "forcado": True})
    elif re.search(r"\b(conven|persuad|minto|engan|intimid|suborn)\b", text):
        forced.update({"tipo": "pericia", "pericia": "persuasao", "atributo": "essencia", "dificuldade": "medio", "intencao": "influenciar", "forcado": True})
    elif re.search(r"\b(salt|escal|arromb|forc)\b", text):
        forced.update({"tipo": "pericia", "pericia": "atletismo", "atributo": "forca", "dificuldade": "medio", "intencao": "teste", "forcado": True})
    return forced


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def empty_resolution(world: dict, sheet: dict) -> dict:
    return {"linhas": [], "rolagem": None, "mundo": world, "sheet": sheet}


def resolve_action(
    *,
    character,
    world: dict,
    action: str,
    intent: dict,
    seed: str,
    mode: str,
    profile: str,
    abertura: bool,
    now: int,
) -> dict:
    world = json.loads(json.dumps(world))
    sheet = json.loads(json.dumps(character.sheet or {}))
    if abertura:
        return empty_resolution(world, sheet)
    if _repeat_failure(world, action):
        previous = world.get("ultimaResolucao") or empty_resolution(world, sheet)
        previous = json.loads(json.dumps(previous))
        previous["mundo"] = world
        previous["sheet"] = sheet
        previous["linhas"] = list(world.get("ultimaLinhas") or previous.get("linhas") or [])
        note = "A situação não mudou: a falha anterior permanece, sem nova rolagem."
        if note not in previous["linhas"]:
            previous["linhas"] = [note, *previous["linhas"]]
        return previous

    _tick_conditions(world)
    if int(world.get("vida") or 0) <= 0 and not world.get("morto") and not (world.get("morte") or {}).get("estavel"):
        return _death_save(character, world, sheet, seed, mode, profile)

    intent = _force_risky(action, intent)
    _maybe_crime(world, action, seed)
    if intent.get("intencao") in {"descansar_curto", "descanso_curto"} or "descanso curto" in _fold(action):
        return _short_rest(character, world, sheet, mode)
    if intent.get("intencao") in {"descansar_longo", "descanso_longo"} or "descanso longo" in _fold(action):
        return _long_rest(character, world, sheet, mode, now)

    if intent.get("intencao") in {"ativar_transformacao", "transformar"} or re.search(
        r"\b(transform\w*|despertar|entro na forma|ativar forma)\b", _fold(action)
    ):
        return _transform(character, world, sheet, seed, mode, profile)
    if intent.get("tipo") == "ataque" or intent.get("intencao") == "atacar":
        return _attack(character, world, sheet, intent, seed, mode, profile)
    if intent.get("tipo") in {"pericia", "atributo", "salvaguarda"}:
        return _check(character, world, sheet, intent, seed, mode, profile, action)
    return empty_resolution(world, sheet)


def _maybe_crime(world: dict, action: str, seed: str) -> None:
    from app.engine.world import add_stars, notice_crime

    text = _fold(action)
    crime = ""
    if "homic" in text or re.search(r"\b(mato|matar|assassino)\b", text):
        crime = "homicidio"
    elif "assalto" in text or "roubo armado" in text:
        crime = "roubo"
    elif "furto" in text or "pungo" in text or "roubo a carteira" in text:
        crime = "furto"
    if not crime:
        return
    noticed = notice_crime(seed, 10, list(world.get("testemunhas") or [12]))
    stars = add_stars(world, crime, noticed)
    world["ultimoCrime"] = {"crime": crime, "visto": noticed, "estrelas": stars}


def _repeat_failure(world: dict, action: str) -> bool:
    last = world.get("ultimaAcao") or ""
    if not last or _fold(last) != _fold(action):
        return False
    roll = world.get("ultimaRolagem") or {}
    return roll.get("resultado") == "falha"


def _tick_conditions(world: dict) -> None:
    timers = dict(world.get("condicaoRodadas") or {})
    active = []
    for name in list(world.get("condicoes") or []):
        if name not in timers:
            active.append(name)
            continue
        timers[name] = int(timers[name]) - 1
        if timers[name] > 0:
            active.append(name)
        else:
            timers.pop(name, None)
    world["condicoes"] = active
    world["condicaoRodadas"] = timers


def _bonus_and_sides(character, sheet: dict, world: dict, *, kind: str, ability: str, proficient: bool) -> tuple[int, bool, bool, list[str]]:
    notes = []
    ability_mod = modifier(character.attributes.get(ability, 10))
    prof = proficiency_bonus(sheet) if proficient else 0
    if ability in set(sheet.get("especializacao") or []):
        prof += proficiency_bonus(sheet)
    flat = ability_mod + prof
    exhaustion = int(world.get("exaustao") or 0)
    if exhaustion:
        flat -= 2 * exhaustion
        notes.append(f"exaustão −{2 * exhaustion}")
    advantage = False
    disadvantage = False
    conditions = set(world.get("condicoes") or [])
    if "envenenado" in conditions and kind in {"ataque", "pericia", "atributo"}:
        disadvantage = True
        notes.append("envenenado")
    if "cego" in conditions and kind == "ataque":
        disadvantage = True
    if "caido" in conditions and kind == "ataque":
        disadvantage = True
        notes.append("caído")
    if "invisivel" in conditions and kind == "ataque":
        advantage = True
    if kind == "salvaguarda" and ability in {"forca", "agilidade"} and conditions & {"atordoado", "paralisado", "inconsciente", "petrificado"}:
        notes.append("falha automática")
        return -100, False, False, notes
    return flat, advantage, disadvantage, notes


def _merge_advantage(intent_flag: str, advantage: bool, disadvantage: bool) -> tuple[bool, bool]:
    if intent_flag == "vantagem":
        advantage = True
    elif intent_flag == "desvantagem":
        disadvantage = True
    if advantage and disadvantage:
        return False, False
    return advantage, disadvantage


def _check(character, world, sheet, intent, seed, mode, profile, action) -> dict:
    if intent.get("tipo") == "pericia" and intent.get("pericia"):
        ability = SKILLS[intent["pericia"]]
        label = SKILL_NAMES[intent["pericia"]]
        proficient = intent["pericia"] in set(sheet.get("pericias") or [])
    else:
        ability = intent.get("atributo") or "vigor"
        label = "Salvaguarda de " + ATTR_NAMES.get(ability, ability) if intent.get("tipo") == "salvaguarda" else ATTR_NAMES.get(ability, ability)
        proficient = ability in set(sheet.get("salvaguardas") or []) if intent.get("tipo") == "salvaguarda" else False
    flat, advantage, disadvantage, notes = _bonus_and_sides(
        character, sheet, world, kind="salvaguarda" if intent.get("tipo") == "salvaguarda" else "pericia", ability=ability, proficient=proficient
    )
    if intent.get("pericia") == "furtividade" and intent.get("intencao") == "esconder":
        dc = 15
    elif intent.get("intencao") == "influenciar" or intent.get("pericia") in SOCIAL:
        dc = max(15, 10)
        attitude = str(world.get("atitudeAlvo") or "indiferente")
        if attitude == "amigavel":
            advantage = True
        elif attitude == "hostil":
            disadvantage = True
    else:
        dc = dc_from_label(intent.get("dificuldade") or "medio", mode=mode, profile=profile)
    dc = max(5, min(dc, 20 if mode != "saga" else {"facil": 20, "normal": 25, "brutal": 30}.get(profile, 25)))
    advantage, disadvantage = _merge_advantage(intent.get("vantagem") or "nenhuma", advantage, disadvantage)
    if flat <= -100:
        linha = f"🛡️ {label}: falha automática"
        roll = {"dados": [], "modo": "automatico", "usado": 0, "mod": flat, "prof": 0, "total": 0, "cd": dc, "resultado": "falha", "margem": -dc}
        return _finish(character, world, sheet, action, [linha], roll, intent, success=False, seed=seed, mode=mode, profile=profile)
    rng = roller(seed + "|teste")
    dice, used, modo = roll_d20(rng, advantage, disadvantage)
    total = used + flat
    # 20 e 1 naturais não decidem testes nem salvaguardas.
    success = total >= dc
    dice_txt = f"[{', '.join(str(n) for n in dice)}]" if len(dice) > 1 else str(dice[0])
    modo_txt = f", {modo} {dice_txt}" if modo != "normal" else ""
    shown = dice[0] if modo == "normal" else used
    linha = f"🎲 {label} ({ATTR_NAMES.get(ability, ability)}){modo_txt}: {shown} + {flat} = {total} vs CD {dc} — {'sucesso' if success else 'falha'}"
    if intent.get("forcado"):
        linha += " · teste obrigatório"
    if notes:
        linha += " · " + ", ".join(notes)
    roll = {
        "dados": dice, "modo": modo, "usado": used, "mod": flat, "prof": proficiency_bonus(sheet) if proficient else 0,
        "total": total, "cd": dc, "resultado": "sucesso" if success else "falha", "margem": total - dc,
    }
    return _finish(character, world, sheet, action, [linha], roll, intent, success=success, seed=seed, mode=mode, profile=profile)


def _attack(character, world, sheet, intent, seed, mode, profile) -> dict:
    level = int(sheet.get("nivel") or 1)
    ability = "agilidade" if modifier(character.attributes.get("agilidade", 10)) > modifier(character.attributes.get("forca", 10)) else "forca"
    flat, advantage, disadvantage, notes = _bonus_and_sides(
        character, sheet, world, kind="ataque", ability=ability, proficient=True
    )
    capped, cut = clamp(flat, attack_bonus_cap(level))
    if cut:
        notes.append(f"teto {_signed(attack_bonus_cap(level))}")
        flat = capped
    advantage, disadvantage = _merge_advantage(intent.get("vantagem") or "nenhuma", advantage, disadvantage)
    enemy = _ensure_enemy(world)
    ac = min(int(enemy.get("ca") or 13), armor_class_cap(level) + 2)
    rng = roller(seed + "|ataque")
    dice, used, modo = roll_d20(rng, advantage, disadvantage)
    total = used + flat
    crit = used == 20
    fumble = used == 1
    hit = crit or (not fumble and total >= ac)
    linhas = []
    damage = 0
    if hit:
        sides = 8
        rolls = [roll_die(rng, sides)]
        if crit:
            rolls.append(roll_die(rng, sides))
        damage = sum(rolls) + modifier(character.attributes.get(ability, 10))
        damage = max(0, damage)
        from app.engine.combat import apply_resistance

        damage = apply_resistance(damage, "cortante", enemy)
        enemy["vida"] = max(0, int(enemy.get("vida") or 0) - damage)
        dice_label = f"{len(rolls)}d{sides}"
        if crit:
            linhas.append(
                f"⚔️ Ataque: 20 natural — crítico · dano {dice_label} + {modifier(character.attributes.get(ability, 10))} = {damage} cortante"
            )
        else:
            shown = used
            linhas.append(f"⚔️ Ataque: {shown} + {flat} = {total} vs CA {ac} — acerto · dano 1d8 + {modifier(character.attributes.get(ability, 10))} = {damage} cortante")
    else:
        shown = used
        extra = "1 natural — erro" if fumble else f"{shown} + {flat} = {total} vs CA {ac} — erro"
        linhas.append(f"⚔️ Ataque: {extra}")
    if notes:
        linhas[-1] += " · " + ", ".join(notes)
    success = hit
    roll = {
        "dados": dice, "modo": modo, "usado": used, "mod": flat, "total": total, "cd": ac,
        "resultado": "sucesso" if hit else "falha", "margem": total - ac, "dano": damage, "critico": crit,
    }
    return _finish(character, world, sheet, "", linhas, roll, intent, success=success, seed=seed, mode=mode, profile=profile, damage_already=True)


def _ensure_enemy(world: dict) -> dict:
    enemies = list(world.get("inimigos") or [])
    if not enemies:
        enemies = [{"id": "opositor", "nome": "Opositor", "vida": 11, "vidaMax": 11, "ca": 13, "zona": "corpo"}]
    world["inimigos"] = enemies
    return enemies[0]


def _finish(character, world, sheet, action, linhas, roll, intent, *, success, seed, mode, profile, damage_already=False) -> dict:
    if not success and not damage_already and intent.get("falha") in RISK_DICE:
        amount = _risk_damage(seed, intent["falha"], int(sheet.get("nivel") or 1))
        _apply_damage(world, amount, mode=mode, profile=profile, crit=False)
        linhas.append(f"Dano {amount}. Vida {world.get('vida')}/{world.get('vidaMax')}.")
    if not success and intent.get("condicao"):
        _add_condition(world, intent["condicao"], 3)
        linhas.append(f"Condição: {intent['condicao']}.")
    if success and roll and int(roll.get("margem") or 0) >= 5 and not sheet.get("inspiracaoGanha"):
        sheet["inspiracao"] = True
        sheet["inspiracaoGanha"] = True
        linhas.append("✨ Inspiração Heroica disponível.")
    world["ultimaAcao"] = action
    world["ultimaRolagem"] = roll
    world["ultimaLinhas"] = list(linhas)
    world["vida"] = max(0, int(world.get("vida") or 0))
    return {"linhas": linhas, "rolagem": roll, "mundo": world, "sheet": sheet}


def _risk_damage(seed: str, label: str, level: int) -> int:
    count, sides, divisor = RISK_DICE[label]
    rng = roller(seed + "|risco")
    bonus = level // divisor
    return sum(roll_die(rng, sides) for _ in range(count)) + bonus


def _apply_damage(world: dict, amount: int, *, mode: str, profile: str, crit: bool) -> None:
    amount = max(0, int(amount))
    temp = int(world.get("vidaTemp") or 0)
    if temp:
        absorbed = min(temp, amount)
        world["vidaTemp"] = temp - absorbed
        amount -= absorbed
    hp = int(world.get("vida") or 0)
    if hp <= 0 and amount > 0:
        fails = 2 if crit else 1
        _death_fail(world, fails, mode, profile)
        return
    hp -= amount
    if hp > 0:
        world["vida"] = hp
        return
    overflow = -hp
    world["vida"] = 0
    world.setdefault("morte", {"sucessos": 0, "falhas": 0, "estavel": False})
    _add_condition(world, "inconsciente", 0)
    _add_condition(world, "caido", 0)
    max_hp = int(world.get("vidaMax") or 1)
    if mode == "saga" and profile == "brutal" and overflow >= max_hp:
        world["morto"] = True
        world["causaMorte"] = "dano_massivo"


def _add_condition(world: dict, name: str, rounds: int) -> None:
    if name not in CONDITIONS:
        return
    current = list(world.get("condicoes") or [])
    if name not in current:
        current.append(name)
    world["condicoes"] = current
    if rounds:
        timers = dict(world.get("condicaoRodadas") or {})
        timers[name] = rounds
        world["condicaoRodadas"] = timers


def _death_fail(world: dict, fails: int, mode: str, profile: str) -> None:
    death = dict(world.get("morte") or {"sucessos": 0, "falhas": 0, "estavel": False})
    death["falhas"] = int(death.get("falhas") or 0) + fails
    world["morte"] = death
    if death["falhas"] >= 3:
        _resolve_collapse(world, mode, profile)


def _resolve_collapse(world: dict, mode: str, profile: str) -> None:
    if mode == "saga" and profile != "missao":
        if profile == "brutal" and not (world.get("contrato") or {}).get("julgamento"):
            world["morto"] = True
            world["causaMorte"] = "salvaguardas"
            return
        if not world.get("julgamentoUsado"):
            world["julgamentoDisponivel"] = True
        world["morto"] = not world.get("julgamentoDisponivel")
        if world["morto"]:
            world["causaMorte"] = "salvaguardas"
        return
    world["vida"] = 1
    world["morte"] = {"sucessos": 0, "falhas": 0, "estavel": False}
    world["condicoes"] = [name for name in world.get("condicoes") or [] if name not in {"inconsciente", "caido"}]
    world["derrota"] = True
    world["objetivoStatus"] = "falhou"


def apply_death_roll(world: dict, rolled: int, mode: str, profile: str) -> str:
    death = dict(world.get("morte") or {"sucessos": 0, "falhas": 0, "estavel": False})
    if rolled == 20:
        world["vida"] = 1
        world["condicoes"] = [name for name in world.get("condicoes") or [] if name not in {"inconsciente", "caido"}]
        world["morte"] = {"sucessos": 0, "falhas": 0, "estavel": False}
        linha = "💀 Contra a morte: 20 natural — volta com 1 PV"
    elif rolled == 1:
        death["falhas"] = int(death.get("falhas") or 0) + 2
        world["morte"] = death
        linha = f"💀 Contra a morte: 1 — duas falhas (sucessos {death.get('sucessos', 0)} · falhas {death['falhas']})"
        if death["falhas"] >= 3:
            _resolve_collapse(world, mode, profile)
    elif rolled >= 10:
        death["sucessos"] = int(death.get("sucessos") or 0) + 1
        world["morte"] = death
        linha = f"💀 Contra a morte: {rolled} — sucesso (sucessos {death['sucessos']} · falhas {death.get('falhas', 0)})"
        if death["sucessos"] >= 3:
            death["estavel"] = True
            world["morte"] = death
            linha += " · estável"
    else:
        death["falhas"] = int(death.get("falhas") or 0) + 1
        world["morte"] = death
        linha = f"💀 Contra a morte: {rolled} — falha (sucessos {death.get('sucessos', 0)} · falhas {death['falhas']})"
        if death["falhas"] >= 3:
            _resolve_collapse(world, mode, profile)
    return linha


def _death_save(character, world, sheet, seed, mode, profile) -> dict:
    rng = roller(seed + "|morte")
    rolled = roll_die(rng, 20)
    linha = apply_death_roll(world, rolled, mode, profile)
    roll = {"dados": [rolled], "modo": "normal", "usado": rolled, "total": rolled, "cd": 10, "resultado": "sucesso" if rolled >= 10 else "falha"}
    world["ultimaRolagem"] = roll
    world["ultimaLinhas"] = [linha]
    return {"linhas": [linha], "rolagem": roll, "mundo": world, "sheet": sheet}


def _short_rest(character, world, sheet, mode) -> dict:
    if mode != "saga" and world.get("descansoCurto"):
        linha = "Descanso curto recusado: a missão já teve um."
        return {"linhas": [linha], "rolagem": None, "mundo": world, "sheet": sheet}
    world["descansoCurto"] = True
    dice = int(world.get("dadosVida") if world.get("dadosVida") is not None else sheet.get("dadosVidaMax") or 1)
    healed = 0
    if dice > 0 and int(world.get("vida") or 0) < int(world.get("vidaMax") or 1):
        sides = int(sheet.get("dado") or 8)
        rng = roller(str(world.get("idRolagem") or "descanso") + "|curto")
        healed = max(1, roll_die(rng, sides) + modifier(character.attributes.get("vigor", 10)))
        world["vida"] = min(int(world["vidaMax"]), int(world["vida"]) + healed)
        world["dadosVida"] = dice - 1
    reserva = sheet.get("reserva")
    pe = int(world.get("pe") or 0)
    pe_max = int(world.get("peMax") or sheet.get("peMax") or 0)
    if reserva == "marcial":
        world["pe"] = min(pe_max, pe + pe_max // 2)
    elif reserva == "pacto":
        world["pe"] = pe_max
    elif reserva in {"plena", "meia"} and not world.get("recuperacaoArcana"):
        level = int(sheet.get("nivel") or 1)
        regain = (level + 1) // 2 + proficiency_bonus(sheet)
        world["pe"] = min(pe_max, pe + regain)
        world["recuperacaoArcana"] = True
    linha = f"Descanso curto. Recupera {healed} PV. Vida {world['vida']}/{world['vidaMax']}. PE {world.get('pe')}/{pe_max}."
    return {"linhas": [linha], "rolagem": None, "mundo": world, "sheet": sheet}


def _long_rest(character, world, sheet, mode, now: int) -> dict:
    if mode != "saga":
        return {"linhas": ["Descanso longo só existe em saga, num lugar seguro."], "rolagem": None, "mundo": world, "sheet": sheet}
    if not (world.get("seguro") or world.get("casa")):
        return {"linhas": ["O lugar não é seguro. O descanso longo não acontece."], "rolagem": None, "mundo": world, "sheet": sheet}
    last = int(world.get("ultimoDescansoLongo") or 0)
    if last and now - last < 16 * 3600:
        return {"linhas": ["Ainda não se passaram 16 horas desde o último descanso longo."], "rolagem": None, "mundo": world, "sheet": sheet}
    world["vida"] = int(world.get("vidaMax") or 1)
    world["vidaTemp"] = 0
    world["dadosVida"] = int(sheet.get("dadosVidaMax") or 1)
    world["pe"] = int(world.get("peMax") or sheet.get("peMax") or 0)
    world["recuperacaoArcana"] = False
    world["descansoCurto"] = False
    if int(world.get("exaustao") or 0) > 0:
        world["exaustao"] = int(world["exaustao"]) - 1
    world["ultimoDescansoLongo"] = now
    world["condicoes"] = []
    linha = f"Descanso longo. Vida {world['vida']}/{world['vidaMax']}. Exaustão {world.get('exaustao', 0)}."
    return {"linhas": [linha], "rolagem": None, "mundo": world, "sheet": sheet}


def _transform(character, world, sheet, seed, mode, profile) -> dict:
    from app.catalog import transformation_offer
    from app.engine.math import temp_hp_cap

    level = int(sheet.get("nivel") or 1)
    forms = transformation_offer(
        sheet.get("racaId") or "",
        sheet.get("classeId") or "",
        level,
        int(sheet.get("estagio") or 0),
        sheet.get("subclasse") or "",
    )
    rank = {"menor": 1, "maior": 2, "suprema": 3}
    limit = 3 if mode == "saga" else 2
    if mode == "pvp" and level < 11:
        limit = 1
    allowed = [form for form in forms if rank[form["grau"]] <= limit and not (mode != "saga" and form["grau"] == "suprema")]
    if not allowed:
        return {"linhas": ["A forma pedida não cabe no nível, no estágio ou no modo."], "rolagem": None, "mundo": world, "sheet": sheet}
    form = allowed[-1]
    active = list(world.get("formas") or [])
    active_grades = {item.get("grau") for item in active}
    if form["grau"] != "menor" and any(grade != "menor" for grade in active_grades):
        return {"linhas": ["Já há uma forma Maior ou Suprema. Só uma delas por vez, e a outra precisa ser Menor."], "rolagem": None, "mundo": world, "sheet": sheet}
    if mode != "saga" and form["grau"] == "maior" and world.get("maiorUsada"):
        return {"linhas": ["A missão já usou a única forma Maior."], "rolagem": None, "mundo": world, "sheet": sheet}
    cap = temp_hp_cap(level, form["grau"])
    gained = min(cap, {"menor": 2, "maior": 4, "suprema": 6}[form["grau"]] * level)
    world["vidaTemp"] = max(int(world.get("vidaTemp") or 0), gained)
    active.append({"id": form["id"], "grau": form["grau"], "nome": form["nome"], "rodadas": 10, "origem": form["origem"]})
    world["formas"] = active
    if form["grau"] == "maior" and mode != "saga":
        world["maiorUsada"] = True
    linhas = [f"Forma {form['nome']} ({form['grau']}). PV temporários {world['vidaTemp']} (teto {cap})."]
    roll = None
    if form["grau"] in {"maior", "suprema"}:
        cd = 16 if form["grau"] == "suprema" else 14
        ability = modifier(character.attributes.get("percepcao", 10))
        prof = proficiency_bonus(sheet) if "percepcao" in set(sheet.get("salvaguardas") or []) else 0
        rng = roller(seed + "|dominio")
        dice, used, modo = roll_d20(rng, False, False)
        total = used + ability + prof - 2 * int(world.get("exaustao") or 0)
        success = total >= cd
        roll = {"dados": dice, "usado": used, "total": total, "cd": cd, "resultado": "sucesso" if success else "falha"}
        linhas.append(f"🛡️ Domínio (Percepção): {used} + {ability + prof} = {total} vs CD {cd} — {'sucesso' if success else 'falha'}")
        if not success:
            world["dominioFalhou"] = True
            linhas.append("Falha no Domínio: o servidor escolhe o alvo mais próximo.")
    return {"linhas": linhas, "rolagem": roll, "mundo": world, "sheet": sheet}


def fresh_world(character, place: str, objective: str) -> dict:
    sheet = character.sheet or {}
    hp = int(sheet.get("vidaMax") or hp_at_level_one("sombra", character.attributes.get("vigor", 10)))
    pe = int(sheet.get("peMax") or 0)
    return {
        "era": "a revelar",
        "saga": "a revelar",
        "lugar": place,
        "quando": "a chegada",
        "vida": hp,
        "vidaMax": hp,
        "vidaTemp": 0,
        "dadosVida": int(sheet.get("dadosVidaMax") or 1),
        "pe": pe,
        "peMax": pe,
        "energia": pe,
        "energiaMax": pe,
        "exaustao": 0,
        "condicoes": [],
        "morte": {"sucessos": 0, "falhas": 0, "estavel": False},
        "inventario": list(sheet.get("equipamento") or ["um pertence pessoal"]),
        "sinais": {},
        "npcs": [],
        "missoes": [{"titulo": "Dar rumo à saga", "status": "ativa", "resumo": objective}],
        "objetivo": objective,
        "objetivoOriginal": objective,
        "objetivoStatus": "ativa",
        "perfil": "normal",
        "inimigos": [],
    }


def technique_dc(level: int, ability_mod: int, prof: int) -> tuple[int, bool]:
    raw = 8 + ability_mod + prof
    return clamp(raw, technique_dc_cap(level))


def attacks_this_turn(class_id: str, level: int, bonus: int = 0) -> int:
    total = extra_attacks(class_id, level) + bonus
    if class_id == "espadachim":
        return total
    return min(5, total)


def format_locked(resolved: dict) -> str:
    payload = {
        "linhas": resolved.get("linhas") or [],
        "rolagem": resolved.get("rolagem"),
        "vida": (resolved.get("mundo") or {}).get("vida"),
        "vidaMax": (resolved.get("mundo") or {}).get("vidaMax"),
        "morto": bool((resolved.get("mundo") or {}).get("morto")),
        "derrota": bool((resolved.get("mundo") or {}).get("derrota")),
    }
    return (
        "RESULTADO_TRAVADO (não contradiga; não invente número, sucesso, PV, item, XP nem morte):\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def contradicts(narrative: str, resolved: dict) -> bool:
    roll = resolved.get("rolagem") or {}
    result = roll.get("resultado")
    text = _fold(narrative)
    if result == "sucesso" and re.search(r"\b(voce falha|nao consegue|erra o golpe|o ataque erra)\b", text):
        return True
    if result == "falha" and re.search(r"\b(voce consegue|voce acerta|o ataque acerta)\b", text):
        return True
    return False
