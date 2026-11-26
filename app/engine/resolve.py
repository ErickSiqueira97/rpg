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
    if tipo not in {"pericia", "atributo", "salvaguarda", "ataque", "tecnica", "nenhum"}:
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
    circulo_raw = teste.get("circulo")
    try:
        circulo = int(circulo_raw) if circulo_raw is not None and str(circulo_raw).strip() != "" else 1
    except (TypeError, ValueError):
        circulo = 1
    return {
        "intencao": str(data.get("intencao") or "nenhum"),
        "tipo": tipo,
        "atributo": atributo,
        "pericia": pericia,
        "dificuldade": str(teste.get("dificuldade") or "medio"),
        "vantagem": vantagem,
        "condicao": condicao,
        "falha": falha,
        "alvo": str(teste.get("alvo") or ""),
        "circulo": max(0, min(5, circulo)),
        "via": str(teste.get("via") or ""),
        "cobertura": str(teste.get("cobertura") or ""),
        "zona": str(teste.get("zona") or ""),
        "alcance": str(teste.get("alcance") or ""),
        "cura": bool(teste.get("cura")),
        "usar_inspiracao": bool(data.get("usar_inspiracao")),
        "forcado": False,
    }


def _force_risky(action: str, intent: dict) -> dict:
    if intent.get("tipo") not in {"nenhum", "", None}:
        return intent
    text = _fold(action)
    forced = dict(intent)
    if re.search(r"\b(ataco|ataque|atacar|golpe|corto|soco|espada|flecha|disparo)\b", text):
        forced.update({"tipo": "ataque", "intencao": "atacar", "atributo": "forca", "forcado": True})
    elif re.search(r"\b(tecnica|magia|conjuro|lanco|feitico|selos?)\b", text):
        forced.update({"tipo": "tecnica", "intencao": "tecnica", "circulo": 1, "forcado": True})
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


def _sync_pe(world: dict, sheet: dict, value: int) -> int:
    pe_max = int(world.get("peMax") or world.get("energiaMax") or sheet.get("peMax") or 0)
    clamped = max(0, min(pe_max, int(value))) if pe_max else max(0, int(value))
    world["peMax"] = pe_max
    world["energiaMax"] = pe_max
    world["pe"] = clamped
    world["energia"] = clamped
    return clamped


def _wants_inspiration(action: str, intent: dict) -> bool:
    if intent.get("usar_inspiracao"):
        return True
    text = _fold(action)
    return re.search(r"\b(gast\w*|us\w*)\s+(a\s+|minha\s+)?inspiracao\b", text) is not None


def _spend_inspiration(sheet: dict, seed: str, current_used: int, advantage: bool, disadvantage: bool) -> tuple[int, str | None]:
    if not sheet.get("inspiracao"):
        return current_used, None
    sheet["inspiracao"] = False
    rng = roller(seed + "|inspiracao")
    reroll = roll_die(rng, 20)
    chosen = max(current_used, reroll) if not disadvantage else reroll
    return chosen, f"✨ Inspiração Heroica gasta: novo d20 = {reroll}"


def _end_form(world: dict, form: dict) -> list[str]:
    lines = [f"Forma {form.get('nome') or form.get('id')} encerrada."]
    grade = form.get("grau")
    if grade == "maior":
        world["exaustao"] = min(6, int(world.get("exaustao") or 0) + 1)
        lines.append("Exaustão +1 ao terminar forma Maior.")
    elif grade == "suprema":
        world["exaustao"] = min(6, int(world.get("exaustao") or 0) + 2)
        _add_condition(world, "incapacitado", 1)
        lines.append("Exaustão +2 e Incapacitado por 1 rodada ao terminar forma Suprema.")
    return lines


def _roll_dominion(character, world: dict, sheet: dict, seed: str, grade: str, mode: str, *, stacked: bool = False) -> tuple[bool, list[str], dict]:
    base_cd = {"menor": 12, "maior": 14, "suprema": 16}.get(grade, 14)
    cd = base_cd + (1 if stacked else 0)
    ability = modifier(character.attributes.get("percepcao", 10))
    prof = proficiency_bonus(sheet) if "percepcao" in set(sheet.get("salvaguardas") or []) else 0
    rng = roller(seed + "|dominio")
    dice, used, _modo = roll_d20(rng, False, False)
    penalty = 2 * int(world.get("exaustao") or 0)
    total = used + ability + prof - penalty
    success = total >= cd
    roll = {"dados": dice, "usado": used, "total": total, "cd": cd, "resultado": "sucesso" if success else "falha"}
    lines = [f"🛡️ Domínio (Percepção): {used} + {ability + prof} = {total} vs CD {cd} — {'sucesso' if success else 'falha'}"]
    if not success:
        world["dominioFalhou"] = True
        lines.append("Falha no Domínio: o servidor escolhe o alvo mais próximo.")
        if mode == "saga" and str(world.get("perfil") or "") == "brutal":
            fails = int(world.get("falhasDominio") or 0) + 1
            world["falhasDominio"] = fails
            if fails >= 3 and not world.get("cicatrizDominio"):
                world["cicatrizDominio"] = "percepcao"
                lines.append("3 falhas de Domínio no Brutal: cicatriz permanente.")
    return success, lines, roll


def _tick_forms(character, world: dict, sheet: dict, seed: str, mode: str) -> list[str]:
    active = list(world.get("formas") or [])
    if not active:
        return []
    lines: list[str] = []
    remaining: list[dict] = []
    incapacitated = int(world.get("vida") or 0) <= 0 or "incapacitado" in set(world.get("condicoes") or [])
    for form in active:
        rounds = int(form.get("rodadas") or 0) - 1
        if incapacitated or rounds <= 0:
            lines.extend(_end_form(world, form))
        else:
            updated = dict(form)
            updated["rodadas"] = rounds
            remaining.append(updated)
    world["formas"] = remaining
    if not remaining:
        world["vidaTemp"] = 0
        return lines
    hp = int(world.get("vida") or 0)
    hp_max = int(world.get("vidaMax") or 1)
    if hp * 2 <= hp_max:
        grades = [item.get("grau") for item in remaining]
        needs_check = any(g in {"maior", "suprema"} for g in grades) or sheet.get("racaId") == "licantropo"
        if needs_check:
            top = "suprema" if "suprema" in grades else ("maior" if "maior" in grades else "menor")
            _ok, dom_lines, _roll = _roll_dominion(
                character, world, sheet, seed + "|turno", top, mode, stacked=len(remaining) > 1
            )
            lines.extend(dom_lines)
    return lines


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
    world["tecnicaUsadaNoTurno"] = False
    world["peGastoNoTurno"] = 0
    world["defesa"] = False
    form_lines = _tick_forms(character, world, sheet, seed, mode)
    if int(world.get("vida") or 0) <= 0 and not world.get("morto") and not (world.get("morte") or {}).get("estavel"):
        res = _death_save(character, world, sheet, seed, mode, profile)
        if form_lines:
            res["linhas"] = [*form_lines, *res["linhas"]]
        return res

    intent = _force_risky(action, intent)
    folded = _fold(action)
    if (world.get("contrato") or {}).get("travado") and (world.get("contrato") or {}).get("fuga") is False:
        if intent.get("intencao") == "fugir" or re.search(r"\b(fujo|fugir|escapar da luta)\b", folded):
            return {"linhas": [*form_lines, "Fuga bloqueada pelo contrato da cena."], "rolagem": None, "mundo": world, "sheet": sheet}

    if re.search(r"\b(encerr\w*|desativ\w*)\s+(a\s+)?forma\b", folded) and world.get("formas"):
        ended: list[str] = []
        for form in list(world.get("formas") or []):
            ended.extend(_end_form(world, form))
        world["formas"] = []
        world["vidaTemp"] = 0
        return {"linhas": [*form_lines, *ended], "rolagem": None, "mundo": world, "sheet": sheet}

    move_lines = _maybe_move(character, world, sheet, intent, folded, seed, mode, profile)
    if re.search(r"\b(esquivo|esquivar|defendo|postura defensiva)\b", folded) or intent.get("intencao") in {"esquivar", "defender"}:
        world["defesa"] = True

    if sheet.get("classeId") == "furioso" and re.search(r"\b(entr\w*\s+em\s+furia|ativ\w*\s+furia)\b", folded):
        if not world.get("furiaAtiva"):
            world["furiaAtiva"] = True
            return {"linhas": [*form_lines, *move_lines, "🔥 Fúria ativada: resistência a dano físico e bônus no corpo a corpo."], "rolagem": None, "mundo": world, "sheet": sheet}

    if sheet.get("classeId") == "espadachim" and "retomar folego" in folded and not world.get("retomarFolegoUsado"):
        world["retomarFolegoUsado"] = True
        rng = roller(seed + "|retomar")
        healed = roll_die(rng, 10) + int(sheet.get("nivel") or 1)
        world["vida"] = min(int(world.get("vidaMax") or healed), int(world.get("vida") or 0) + healed)
        return {"linhas": [*form_lines, *move_lines, f"💨 Retomar Fôlego: recupera {healed} PV. Vida {world['vida']}/{world['vidaMax']}."], "rolagem": None, "mundo": world, "sheet": sheet}

    crime_lines = _maybe_crime(character, sheet, world, action, seed)
    if intent.get("intencao") in {"descansar_curto", "descanso_curto"} or "descanso curto" in folded:
        res = _short_rest(character, world, sheet, mode)
    elif intent.get("intencao") in {"descansar_longo", "descanso_longo"} or "descanso longo" in folded:
        res = _long_rest(character, world, sheet, mode, now)
    elif intent.get("intencao") in {"ativar_transformacao", "transformar"} or re.search(
        r"\b(transform\w*|despertar|entro na forma|ativar forma)\b", folded
    ):
        res = _transform(character, world, sheet, seed, mode, profile)
    elif intent.get("tipo") == "tecnica" or intent.get("intencao") == "tecnica":
        res = _technique(character, world, sheet, intent, seed, mode, profile, action)
    elif intent.get("tipo") == "ataque" or intent.get("intencao") == "atacar":
        res = _attack(character, world, sheet, intent, seed, mode, profile, action)
    elif intent.get("tipo") in {"pericia", "atributo", "salvaguarda"}:
        res = _check(character, world, sheet, intent, seed, mode, profile, action, now)
    else:
        res = empty_resolution(world, sheet)
        if world.get("defesa"):
            res["linhas"] = ["🛡️ Postura defensiva (+2 CA e Desvantagem nos ataques contra você)."]
    prefix = [*form_lines, *move_lines, *crime_lines]
    if prefix:
        res["linhas"] = [*prefix, *(res.get("linhas") or [])]
        res["mundo"]["ultimaLinhas"] = list(res["linhas"])
    return res


def _maybe_move(character, world: dict, sheet: dict, intent: dict, folded: str, seed: str, mode: str, profile: str) -> list[str]:
    from app.engine.combat import ZONES, opportunity

    before = str(world.get("zona") or "corpo")
    target = str(intent.get("zona") or "")
    if target not in ZONES:
        if re.search(r"\b(longe|afasto|recuo|distancia)\b", folded):
            target = "longe"
        elif re.search(r"\b(perto|aproximo)\b", folded):
            target = "perto"
        elif re.search(r"\b(corpo a corpo|avan[cç]o|colo)\b", folded):
            target = "corpo"
        else:
            return []
    if target == before:
        return []
    world["zona"] = target
    lines = [f"Zona: {before} → {target}."]
    disengage = "desengaj" in folded or intent.get("intencao") == "desengajar"
    living = [item for item in (world.get("inimigos") or []) if int(item.get("vida") or 0) > 0]
    if living and opportunity(before, target, disengage):
        lines.extend(_enemy_turn(character, world, sheet, seed + "|oportunidade", mode, profile, single_opportunity=True))
    return lines


def _maybe_crime(character, sheet: dict, world: dict, action: str, seed: str) -> list[str]:
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
        return []
    proficient = "furtividade" in set(sheet.get("pericias") or [])
    flat, adv, disadv, _notes = _bonus_and_sides(
        character, sheet, world, kind="pericia", ability="agilidade", proficient=proficient
    )
    rng = roller(seed + "|furtividade")
    _dice, used, _modo = roll_d20(rng, adv, disadv)
    stealth_total = used + flat
    witnesses = list(world.get("testemunhas") or [12])
    noticed = notice_crime(seed, stealth_total, witnesses)
    stars = add_stars(world, crime, noticed)
    world["ultimoCrime"] = {"crime": crime, "furtividade": stealth_total, "visto": noticed, "estrelas": stars}
    if noticed:
        return [f"👁️ Furtividade no crime: {used} + {flat} = {stealth_total} — visto (procurado {stars}★)."]
    return [f"👁️ Furtividade no crime: {used} + {flat} = {stealth_total} — sem testemunhas (pista deixada)."]


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


def _roll_d20_for(sheet: dict, rng, advantage: bool, disadvantage: bool) -> tuple[list[int], int, str]:
    dice, used, modo = roll_d20(rng, advantage, disadvantage)
    if sheet.get("racaId") == "pequenino" and used == 1:
        reroll = roll_die(rng, 20)
        if len(dice) == 1:
            dice = [reroll]
            used = reroll
        else:
            idx = dice.index(1)
            dice[idx] = reroll
            used = max(dice) if advantage else min(dice)
    return dice, used, modo


def _bonus_and_sides(character, sheet: dict, world: dict, *, kind: str, ability: str, proficient: bool, skill: str = "") -> tuple[int, bool, bool, list[str]]:
    notes = []
    ability_mod = modifier(character.attributes.get(ability, 10))
    prof = proficiency_bonus(sheet) if proficient else 0
    expertise = set(sheet.get("especializacao") or [])
    if (skill and skill in expertise) or ability in expertise:
        prof += proficiency_bonus(sheet)
    flat = ability_mod + prof
    level = int(sheet.get("nivel") or 1)
    race_id = sheet.get("racaId") or ""
    trait_id = sheet.get("traco") or ""

    if kind == "salvaguarda" and sheet.get("classeId") == "sentinela" and level >= 6:
        aura = max(1, modifier(character.attributes.get("essencia", 10)))
        flat += aura
        notes.append(f"aura +{aura}")

    if trait_id == "forjado_na_luta" and kind in {"ataque", "salvaguarda"}:
        stack = min(3, int(world.get("forjadoAcumulo") or 0))
        if stack:
            flat += stack
            notes.append(f"forjado +{stack}")

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

    if race_id == "miudo":
        if kind == "salvaguarda" and ability in {"intelecto", "percepcao", "essencia"}:
            advantage = True
        if kind == "ataque" and ability == "forca" and sheet.get("classeId") in {"espadachim", "furioso"}:
            disadvantage = True
            notes.append("arma pesada (Miúdo)")
    elif race_id == "meio_gigante" and level >= 5 and ability == "forca" and kind in {"pericia", "atributo"}:
        advantage = True
    elif race_id == "noturno" and world.get("solDireto") and (kind == "ataque" or skill == "percepcao"):
        disadvantage = True
        notes.append("sol direto")
    elif race_id == "morto_andante" and skill == "adestrar_animais":
        disadvantage = True
    elif race_id == "iluminado" and world.get("brilhoAtivo") and skill == "furtividade":
        disadvantage = True
    elif race_id == "estelar" and world.get("impetoAtivo") and kind == "ataque":
        advantage = True

    if trait_id == "olhos_raros" and skill == "percepcao":
        advantage = True
    elif trait_id == "faro_apurado" and skill in {"percepcao", "sobrevivencia"}:
        advantage = True
    elif trait_id == "mutagenico" and skill == "persuasao":
        disadvantage = True

    if world.get("parceiroCaido"):
        from app.engine.world import bond_effect

        if any(bond_effect(int((bond or {}).get("nivel") or 0)) == "vantagem_quando_parceiro_cai" for bond in (world.get("lacos") or {}).values()):
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


def _check(character, world, sheet, intent, seed, mode, profile, action, now: int = 0) -> dict:
    is_influence = intent.get("intencao") == "influenciar" or intent.get("pericia") in SOCIAL
    target_key = _fold(str(intent.get("alvo") or "npc")) or "npc"
    if is_influence:
        cooldowns = dict(world.get("influenciarBloqueado") or {})
        last_fail = cooldowns.get(target_key)
        if last_fail is not None and now - int(last_fail) < 24 * 3600:
            return {
                "linhas": ["Influenciar recusado: aguarde 24 horas após a última falha com esse alvo."],
                "rolagem": None,
                "mundo": world,
                "sheet": sheet,
            }

    if intent.get("tipo") == "pericia" and intent.get("pericia"):
        ability = SKILLS[intent["pericia"]]
        label = SKILL_NAMES[intent["pericia"]]
        proficient = intent["pericia"] in set(sheet.get("pericias") or [])
    else:
        ability = intent.get("atributo") or "vigor"
        label = "Salvaguarda de " + ATTR_NAMES.get(ability, ability) if intent.get("tipo") == "salvaguarda" else ATTR_NAMES.get(ability, ability)
        proficient = ability in set(sheet.get("salvaguardas") or []) if intent.get("tipo") == "salvaguarda" else False
    flat, advantage, disadvantage, notes = _bonus_and_sides(
        character,
        sheet,
        world,
        kind="salvaguarda" if intent.get("tipo") == "salvaguarda" else "pericia",
        ability=ability,
        proficient=proficient,
        skill=intent.get("pericia") or "",
    )
    if intent.get("pericia") == "furtividade" and intent.get("intencao") == "esconder":
        dc = 15
    elif is_influence:
        dc = max(15, 10)
        attitude = str(world.get("atitudeAlvo") or "")
        if not attitude and int(world.get("procurado") or 0) >= 2:
            attitude = "hostil"
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
    dice, used, modo = _roll_d20_for(sheet, rng, advantage, disadvantage)
    insp_line = None
    if _wants_inspiration(action, intent):
        used, insp_line = _spend_inspiration(sheet, seed, used, advantage, disadvantage)
    total = used + flat
    # 20 e 1 naturais não decidem testes nem salvaguardas.
    success = total >= dc
    if is_influence and not success:
        cooldowns = dict(world.get("influenciarBloqueado") or {})
        cooldowns[target_key] = now
        world["influenciarBloqueado"] = cooldowns
    dice_txt = f"[{', '.join(str(n) for n in dice)}]" if len(dice) > 1 else str(dice[0])
    modo_txt = f", {modo} {dice_txt}" if modo != "normal" else ""
    shown = dice[0] if modo == "normal" else used
    linha = f"🎲 {label} ({ATTR_NAMES.get(ability, ability)}){modo_txt}: {shown} + {flat} = {total} vs CD {dc} — {'sucesso' if success else 'falha'}"
    if intent.get("forcado"):
        linha += " · teste obrigatório"
    if notes:
        linha += " · " + ", ".join(notes)
    lines = [linha]
    if insp_line:
        lines.append(insp_line)
    roll = {
        "dados": dice, "modo": modo, "usado": used, "mod": flat, "prof": proficiency_bonus(sheet) if proficient else 0,
        "total": total, "cd": dc, "resultado": "sucesso" if success else "falha", "margem": total - dc,
    }
    return _finish(character, world, sheet, action, lines, roll, intent, success=success, seed=seed, mode=mode, profile=profile)


def _extra_damage(character, world: dict, sheet: dict, rng, *, advantage: bool, hit_index: int) -> tuple[int, list[str]]:
    """No máximo 2 fontes extras de dano por turno (regra de empilhamento)."""
    level = int(sheet.get("nivel") or 1)
    pb = proficiency_bonus(sheet)
    sources: list[tuple[int, str]] = []

    forms = world.get("formas") or []
    if forms:
        grades = {item.get("grau") for item in forms}
        if "suprema" in grades and hit_index == 0:
            sources.append((roll_die(rng, 8) + roll_die(rng, 8), "forma"))
        elif "maior" in grades:
            sources.append((pb, "forma"))
        elif hit_index == 0:
            sources.append((roll_die(rng, 6), "forma"))

    if world.get("elixir") == "furia":
        sources.append((roll_die(rng, 4), "elixir"))

    if sheet.get("classeId") == "sombra" and hit_index == 0 and (advantage or world.get("aliadoProximo")):
        dice_count = (level + 1) // 2
        sneak = sum(roll_die(rng, 6) for _ in range(dice_count))
        sources.append((sneak, f"golpe oculto {dice_count}d6"))

    if sheet.get("classeId") == "furioso" and world.get("furiaAtiva"):
        rage_bonus = 2 if level < 9 else (3 if level < 16 else 4)
        sources.append((rage_bonus, "fúria"))

    chosen = sources[:2]
    return sum(amount for amount, _label in chosen), [label for _amount, label in chosen]


def _attack(character, world, sheet, intent, seed, mode, profile, action: str = "") -> dict:
    from app.engine.combat import apply_resistance, attack_count, cover_bonus, ranged_disadvantage, weapon_profile

    level = int(sheet.get("nivel") or 1)
    class_id = sheet.get("classeId") or "espadachim"
    zone = str(world.get("zona") or "corpo")
    sides, dmg_type, ranged, ability = weapon_profile(class_id, sheet, character.attributes, zone)
    if sheet.get("traco") == "membro_de_aco" and world.get("membroTravado"):
        sides = 4
    if sheet.get("racaId") == "feral":
        feral_die = 8 if (int(sheet.get("estagio") or 0) >= 1 or level >= 5) else 6
        sides = max(sides, feral_die)

    flat, advantage, disadvantage, notes = _bonus_and_sides(
        character, sheet, world, kind="ataque", ability=ability, proficient=True
    )
    if ranged_disadvantage(zone, ranged):
        disadvantage = True
        notes.append("alcance no corpo a corpo")
    capped, cut = clamp(flat, attack_bonus_cap(level))
    if cut:
        notes.append(f"teto {_signed(attack_bonus_cap(level))}")
        flat = capped
    advantage, disadvantage = _merge_advantage(intent.get("vantagem") or "nenhuma", advantage, disadvantage)

    enemy = _ensure_enemy(world)
    cover = str(intent.get("cobertura") or enemy.get("cobertura") or "")
    cover_ac = cover_bonus(cover)
    if cover_ac is None:
        return {"linhas": ["Alvo em cobertura total: não pode ser atingido diretamente."], "rolagem": None, "mundo": world, "sheet": sheet}
    base_ac = int(enemy.get("ca") or 13) + cover_ac
    ac = min(base_ac, armor_class_cap(level) + 2)

    folded = _fold(action)
    surge = False
    if class_id == "espadachim" and level >= 2 and "surto" in folded and not world.get("surtoUsado"):
        surge = True
        world["surtoUsado"] = True
    base_swings = extra_attacks(class_id, level)
    swings = attack_count(base_swings, 0, surge=surge)

    crit_min = 19 if (class_id == "espadachim" and level >= 3 and sheet.get("subclasse") == "Lâmina Campeã") else 20
    linhas = []
    total_damage = 0
    last_roll = None
    any_hit = False

    for swing in range(swings):
        targets = [item for item in (world.get("inimigos") or []) if int(item.get("vida") or 0) > 0]
        if not targets:
            break
        target = targets[0]
        target_ac = min(int(target.get("ca") or 13) + cover_ac, armor_class_cap(level) + 2)
        swing_seed = seed + "|ataque" if swing == 0 else f"{seed}|ataque|{swing}"
        rng = roller(swing_seed)
        dice, used, modo = _roll_d20_for(sheet, rng, advantage, disadvantage)
        insp_line = None
        if swing == 0 and _wants_inspiration(action, intent):
            used, insp_line = _spend_inspiration(sheet, seed, used, advantage, disadvantage)
        total = used + flat
        crit = used >= crit_min
        fumble = used == 1
        hit = crit or (not fumble and total >= target_ac)
        damage = 0
        if hit:
            any_hit = True
            rolls = [roll_die(rng, sides)]
            if crit:
                rolls.append(roll_die(rng, sides))
            extra_dmg, extra_labels = _extra_damage(
                character, world, sheet, rng, advantage=advantage, hit_index=swing
            )
            damage = max(0, sum(rolls) + modifier(character.attributes.get(ability, 10)) + extra_dmg)
            damage = apply_resistance(damage, dmg_type, target)
            target["vida"] = max(0, int(target.get("vida") or 0) - damage)
            total_damage += damage
            dice_label = f"{len(rolls)}d{sides}"
            extra_txt = f" ({', '.join(extra_labels)})" if extra_labels else ""
            if crit and used == 20:
                linhas.append(
                    f"⚔️ Ataque: 20 natural — crítico · dano {dice_label} + {modifier(character.attributes.get(ability, 10))} = {damage} {dmg_type}{extra_txt}"
                )
            else:
                crit_tag = "crítico" if crit else "acerto"
                linhas.append(
                    f"⚔️ Ataque: {used} + {flat} = {total} vs CA {target_ac} — {crit_tag} · dano {dice_label} + {modifier(character.attributes.get(ability, 10))} = {damage} {dmg_type}{extra_txt}"
                )
        else:
            extra = "1 natural — erro" if fumble else f"{used} + {flat} = {total} vs CA {target_ac} — erro"
            linhas.append(f"⚔️ Ataque: {extra}")
        if notes and swing == 0:
            linhas[-1] += " · " + ", ".join(notes)
        if insp_line:
            linhas.append(insp_line)
        if fumble and sheet.get("traco") == "membro_de_aco":
            world["membroTravado"] = True
            linhas.append("Prótese travou no 1 natural.")
        if fumble and world.get("formas"):
            top = "suprema" if any(f.get("grau") == "suprema" for f in world["formas"]) else "maior"
            if top in {"maior", "suprema"} or any(f.get("grau") == "maior" for f in world["formas"]):
                _ok, dom_lines, _droll = _roll_dominion(character, world, sheet, f"{seed}|fumble|{swing}", top, mode)
                linhas.extend(dom_lines)
        last_roll = {
            "dados": dice, "modo": modo, "usado": used, "mod": flat, "total": total, "cd": target_ac,
            "resultado": "sucesso" if hit else "falha", "margem": total - target_ac, "dano": damage, "critico": crit,
        }

    linhas.extend(_enemy_turn(character, world, sheet, seed + "|inimigos", mode, profile))
    roll = last_roll or {"dados": [], "modo": "normal", "usado": 0, "mod": flat, "total": 0, "cd": ac, "resultado": "falha", "margem": -ac, "dano": 0, "critico": False}
    roll["dano"] = total_damage
    roll["resultado"] = "sucesso" if any_hit else "falha"
    return _finish(character, world, sheet, "", linhas, roll, intent, success=any_hit, seed=seed, mode=mode, profile=profile, damage_already=True)


def _technique(character, world: dict, sheet: dict, intent: dict, seed: str, mode: str, profile: str, action: str) -> dict:
    from app.catalog import PE_COST, VIAS
    from app.engine.combat import apply_resistance

    contract = world.get("contrato") or {}
    if contract.get("travado") and contract.get("equipamento") in {"sem_magia", "comum"}:
        return {"linhas": ["Contrato da cena bloqueia técnicas mágicas."], "rolagem": None, "mundo": world, "sheet": sheet}
    if sheet.get("traco") == "nulo":
        return {"linhas": ["Traço Nulo impede o uso de Vias e técnicas."], "rolagem": None, "mundo": world, "sheet": sheet}

    via_id = str(intent.get("via") or sheet.get("viaId") or "")
    reserva = str(sheet.get("reserva") or "nenhuma")
    if not via_id and reserva == "nenhuma":
        return {"linhas": ["A ficha não tem Via nem reserva de energia para técnicas."], "rolagem": None, "mundo": world, "sheet": sheet}
    via = next((item for item in VIAS if item["id"] == via_id), None)
    if via_id == "folego_interior" and set(world.get("condicoes") or []) & {"agarrado", "contido"}:
        return {"linhas": ["Fôlego Interior exige mãos livres: bloqueado por Agarrado/Contido."], "rolagem": None, "mundo": world, "sheet": sheet}

    level = int(sheet.get("nivel") or 1)
    circle = int(intent.get("circulo") if intent.get("circulo") is not None else 1)
    max_circle = 5 if mode != "saga" else 5
    if reserva in {"plena", "meia", "pacto"}:
        from app.engine.sheet import circle_max

        max_circle = max(1, circle_max(reserva, level))
    elif reserva == "marcial":
        max_circle = 1
    if circle > max_circle:
        circle = max_circle

    cost = 0 if circle == 0 else (1 if reserva == "marcial" else PE_COST.get(circle, 2))
    if circle >= 1 and cost > 1 and world.get("tecnicaUsadaNoTurno"):
        return {"linhas": ["Só uma técnica de círculo por turno."], "rolagem": None, "mundo": world, "sheet": sheet}

    pe_cap = pe_per_turn_cap(level)
    spent_turn = int(world.get("peGastoNoTurno") or 0)
    if spent_turn + cost > pe_cap:
        return {"linhas": [f"Teto de PE por turno atingido ({spent_turn}/{pe_cap})."], "rolagem": None, "mundo": world, "sheet": sheet}

    current_pe = int(world.get("pe") if world.get("pe") is not None else world.get("energia") or 0)
    if current_pe < cost:
        return {"linhas": [f"PE insuficiente ({current_pe}/{cost})."], "rolagem": None, "mundo": world, "sheet": sheet}

    _sync_pe(world, sheet, current_pe - cost)
    world["peGastoNoTurno"] = spent_turn + cost
    if circle >= 1 and cost > 1:
        world["tecnicaUsadaNoTurno"] = True

    ability = via["atributo"] if via else "intelecto"
    mod = modifier(character.attributes.get(ability, 10))
    prof = proficiency_bonus(sheet)
    dc, cut = technique_dc(level, mod, prof)
    atk_bonus, _ = clamp(mod + prof, attack_bonus_cap(level))
    rng = roller(seed + "|tecnica")
    dice, used, modo = roll_d20(rng, False, False)
    dmg_type = via["dano"] if via else "energia"
    dice_count = 2 if circle == 0 else (circle + 2)
    linhas = []

    if intent.get("cura") or "cura" in _fold(action):
        healed = sum(roll_die(rng, 6) for _ in range(max(1, circle + 1))) + mod
        healed = max(1, healed)
        if sheet.get("racaId") in {"espirito_amaldicoado", "morto_andante"}:
            healed = max(1, healed // 2)
        world["vida"] = min(int(world.get("vidaMax") or healed), int(world.get("vida") or 0) + healed)
        linhas.append(f"✨ Técnica ({via['nome'] if via else 'Energia'}, -{cost} PE): cura {healed} PV. Vida {world['vida']}/{world['vidaMax']}.")
        roll = {"dados": dice, "modo": modo, "usado": used, "total": used + atk_bonus, "cd": dc, "resultado": "sucesso", "margem": 0, "custoPe": cost}
        return _finish(character, world, sheet, "", linhas, roll, intent, success=True, seed=seed, mode=mode, profile=profile, damage_already=True)

    enemy = _ensure_enemy(world)
    ac = min(int(enemy.get("ca") or 13), armor_class_cap(level) + 2)
    total = used + atk_bonus
    crit = used == 20
    fumble = used == 1
    hit = crit or (not fumble and total >= ac)
    damage = 0
    if hit:
        rolls = [roll_die(rng, 6) for _ in range(dice_count * (2 if crit else 1))]
        damage = max(1, sum(rolls) + mod)
        damage = apply_resistance(damage, dmg_type, enemy)
        enemy["vida"] = max(0, int(enemy.get("vida") or 0) - damage)
        linhas.append(
            f"✨ Técnica ({via['nome'] if via else 'Energia'}, -{cost} PE, CD {dc}): {used} + {atk_bonus} = {total} vs CA {ac} — {'crítico' if crit else 'acerto'} · {damage} {dmg_type}"
        )
    else:
        linhas.append(
            f"✨ Técnica ({via['nome'] if via else 'Energia'}, -{cost} PE, CD {dc}): {'1 natural' if fumble else f'{used} + {atk_bonus} = {total} vs CA {ac}'} — erro"
        )
    if cut:
        linhas[-1] += f" · teto CD {dc}"
    if fumble and via_id == "rancor":
        recoil = roll_die(rng, 6)
        _apply_damage(world, recoil, mode=mode, profile=profile, crit=False, sheet=sheet)
        linhas.append(f"Recuo de Rancor: {recoil} psíquico em si.")
    elif fumble and via_id == "engenho":
        world["engenhoTravado"] = True
        linhas.append("Engenho travou no 1 natural.")

    linhas.extend(_enemy_turn(character, world, sheet, seed + "|inimigos", mode, profile))
    roll = {"dados": dice, "modo": modo, "usado": used, "mod": atk_bonus, "total": total, "cd": ac, "resultado": "sucesso" if hit else "falha", "margem": total - ac, "dano": damage, "custoPe": cost}
    return _finish(character, world, sheet, "", linhas, roll, intent, success=hit, seed=seed, mode=mode, profile=profile, damage_already=True)


def _enemy_turn(character, world: dict, sheet: dict, seed: str, mode: str, profile: str, *, single_opportunity: bool = False) -> list[str]:
    from app.engine.combat import apply_resistance
    from app.engine.sheet import armor_class

    if int(world.get("vida") or 0) <= 0:
        return []
    living = [item for item in (world.get("inimigos") or []) if int(item.get("vida") or 0) > 0]
    if not living:
        return []
    targets = living[:1] if single_opportunity else living[:3]
    player_ac = armor_class(character.attributes, sheet, world)
    disadv = bool(world.get("defesa"))
    lines: list[str] = []
    for index, enemy in enumerate(targets):
        if int(world.get("vida") or 0) <= 0:
            break
        rng = roller(f"{seed}|{index}")
        _dice, used, _modo = roll_d20(rng, False, disadv)
        atk = int(enemy.get("ataque") or 4)
        total = used + atk
        crit = used == 20
        hit = crit or (used != 1 and total >= player_ac)
        name = enemy.get("nome") or "Opositor"
        if not hit:
            lines.append(f"🛡️ {name} ataca: {used} + {atk} = {total} vs CA {player_ac} — erro.")
            continue
        sides = int(enemy.get("dado") or 6)
        rolls = [roll_die(rng, sides)]
        if crit:
            rolls.append(roll_die(rng, sides))
        dmg_type = str(enemy.get("tipoDano") or "contundente")
        raw = max(1, sum(rolls) + int(enemy.get("danoMod") or 2))
        damage = apply_resistance(raw, dmg_type, _character_resistances(sheet, world))
        _apply_damage(world, damage, mode=mode, profile=profile, crit=crit, sheet=sheet)
        tag = "crítico" if crit else "acerto"
        lines.append(f"🛡️ {name} ataca: {used} + {atk} = {total} vs CA {player_ac} — {tag} · {damage} {dmg_type}. Vida {world.get('vida')}/{world.get('vidaMax')}.")
    return lines


def _character_resistances(sheet: dict, world: dict) -> dict:
    resist: set[str] = set()
    vuln: set[str] = set()
    race = sheet.get("racaId") or ""
    if race in {"rochoso", "automato", "morto_andante"}:
        resist.add("veneno")
    if race in {"noturno", "espirito_amaldicoado", "morto_andante", "iluminado"}:
        resist.add("necrotico")
    if race == "iluminado":
        resist.add("radiante")
    if race == "sangue_de_dragao":
        resist.add(str(sheet.get("elemento") or "fogo"))
    if race == "espirito_amaldicoado":
        vuln.add("radiante")
    if sheet.get("classeId") == "furioso" and world.get("furiaAtiva"):
        resist.update({"contundente", "perfurante", "cortante"})
    return {"resistencias": list(resist), "vulnerabilidades": list(vuln), "imunidades": []}


def _ensure_enemy(world: dict) -> dict:
    enemies = list(world.get("inimigos") or [])
    if not enemies:
        enemies = [{"id": "opositor", "nome": "Opositor", "vida": 11, "vidaMax": 11, "ca": 13, "zona": "corpo"}]
    world["inimigos"] = enemies
    return enemies[0]


def _finish(character, world, sheet, action, linhas, roll, intent, *, success, seed, mode, profile, damage_already=False) -> dict:
    if not success and not damage_already and intent.get("falha") in RISK_DICE:
        amount = _risk_damage(seed, intent["falha"], int(sheet.get("nivel") or 1))
        _apply_damage(world, amount, mode=mode, profile=profile, crit=False, sheet=sheet)
        linhas.append(f"Dano {amount}. Vida {world.get('vida')}/{world.get('vidaMax')}.")
    if not success and intent.get("condicao"):
        _add_condition(world, intent["condicao"], 3)
        linhas.append(f"Condição: {intent['condicao']}.")
    if sheet.get("traco") == "forjado_na_luta" and intent.get("tipo") in {"ataque", "salvaguarda"}:
        if success:
            world["forjadoAcumulo"] = 0
        else:
            world["forjadoAcumulo"] = min(3, int(world.get("forjadoAcumulo") or 0) + 1)
    if intent.get("intencao") == "ajudar" and intent.get("alvo"):
        from app.engine.world import raise_bond

        raise_bond(world, str(intent["alvo"])[:60], 1)
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


def _apply_damage(world: dict, amount: int, *, mode: str, profile: str, crit: bool, sheet: dict | None = None) -> None:
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
    max_hp = int(world.get("vidaMax") or 1)
    massive_death = mode == "saga" and profile == "brutal" and overflow >= max_hp
    sheet = sheet or {}
    if not massive_death:
        if sheet.get("racaId") == "oni" and not world.get("oniResistenciaUsada"):
            world["oniResistenciaUsada"] = True
            world["vida"] = 1
            return
        if sheet.get("traco") == "divida_com_fera" and not world.get("dividaFeraUsada"):
            world["dividaFeraUsada"] = True
            world["vida"] = 1
            return
    world["vida"] = 0
    world.setdefault("morte", {"sucessos": 0, "falhas": 0, "estavel": False})
    _add_condition(world, "inconsciente", 0)
    _add_condition(world, "caido", 0)
    if massive_death:
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
    contract = world.get("contrato") or {}
    if mode == "saga" and profile != "missao" and not (contract.get("travado") and contract.get("morte") is False):
        if profile == "brutal" and not contract.get("julgamento"):
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
    advantage = sheet.get("racaId") == "morto_andante"
    dice, rolled, modo = _roll_d20_for(sheet, rng, advantage, False)
    linha = apply_death_roll(world, rolled, mode, profile)
    if rolled == 20 and sheet.get("racaId") == "estelar" and not world.get("impetoUsado"):
        level = int(sheet.get("nivel") or 1)
        world["impetoUsado"] = True
        world["impetoAtivo"] = True
        world["vidaTemp"] = max(int(world.get("vidaTemp") or 0), level)
        linha += f" · Ímpeto do Sobrevivente (+{level} PV temp)"
    roll = {"dados": dice, "modo": modo, "usado": rolled, "total": rolled, "cd": 10, "resultado": "sucesso" if rolled >= 10 else "falha"}
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
    pe = int(world.get("pe") if world.get("pe") is not None else world.get("energia") or 0)
    pe_max = int(world.get("peMax") or sheet.get("peMax") or 0)
    world["peMax"] = pe_max
    if reserva == "marcial":
        _sync_pe(world, sheet, pe + pe_max // 2)
    elif reserva == "pacto":
        _sync_pe(world, sheet, pe_max)
    elif reserva in {"plena", "meia"}:
        used = int(world.get("recuperacaoArcanaUsos") or (1 if world.get("recuperacaoArcana") else 0))
        limit = 2 if sheet.get("classeId") == "grimorista" else 1
        if used < limit:
            level = int(sheet.get("nivel") or 1)
            regain = (level + 1) // 2 + proficiency_bonus(sheet)
            _sync_pe(world, sheet, pe + regain)
            world["recuperacaoArcanaUsos"] = used + 1
            world["recuperacaoArcana"] = True
    linha = f"Descanso curto. Recupera {healed} PV. Vida {world['vida']}/{world['vidaMax']}. PE {world.get('pe', 0)}/{pe_max}."
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
    _sync_pe(world, sheet, int(world.get("peMax") or sheet.get("peMax") or 0))
    world["recuperacaoArcana"] = False
    world["recuperacaoArcanaUsos"] = 0
    world["descansoCurto"] = False
    world["oniResistenciaUsada"] = False
    world["dividaFeraUsada"] = False
    world["impetoUsado"] = False
    if int(world.get("exaustao") or 0) > 0:
        world["exaustao"] = int(world["exaustao"]) - 1
    world["ultimoDescansoLongo"] = now
    world["condicoes"] = []
    if sheet.get("racaId") == "humano":
        sheet["inspiracao"] = True
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
        _ok, dom_lines, roll = _roll_dominion(
            character, world, sheet, seed, form["grau"], mode, stacked=len(active) > 1
        )
        linhas.extend(dom_lines)
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
