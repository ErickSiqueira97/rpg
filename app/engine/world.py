"""Procurado, contrato, laços, julgamento, loja e casa. A IA não altera estes números."""

from __future__ import annotations

from app.engine.math import modifier
from app.engine.rng import roll_die, roller

CRIMES = {"furto": 1, "vandalismo": 1, "agressao": 1, "roubo": 2, "homicidio": 3}

SHOP = {
    "pocao_cura": {"nome": "Poção de Cura", "preco": 50, "cura": (2, 4, 2), "colateral": ""},
    "pocao_maior": {"nome": "Poção de Cura Maior", "preco": 200, "cura": (4, 4, 4), "colateral": ""},
    "tonico": {"nome": "Tônico Instável", "preco": 50, "cura": (4, 4, 4), "colateral": "veneno"},
    "elixir_furia": {"nome": "Elixir de Fúria", "preco": 80, "cura": None, "colateral": "furia"},
    "casa": {"nome": "Casa", "preco": 100, "cura": None, "colateral": "casa"},
}


def notice_crime(seed: str, stealth_total: int, witnesses: list[int]) -> bool:
    if not witnesses:
        return False
    return any(stealth_total < passive for passive in witnesses)


def add_stars(world: dict, crime: str, noticed: bool) -> int:
    gain = CRIMES.get(crime, 0)
    if not noticed:
        world["pista"] = True
        return int(world.get("procurado") or 0)
    stars = min(5, int(world.get("procurado") or 0) + gain)
    world["procurado"] = stars
    if stars >= 1:
        world["atitudeMercadores"] = "indiferente" if stars == 1 else "hostil" if stars >= 3 else "indiferente"
    if stars >= 3:
        world["atitudeMercadores"] = "hostil"
    return stars


def merchant_sells(world: dict) -> bool:
    stars = int(world.get("procurado") or 0)
    if stars >= 5 and world.get("tipo") == "saga":
        return False
    if stars >= 3:
        return False
    return True


def price(world: dict, base: int) -> int:
    if int(world.get("procurado") or 0) >= 4:
        return base * 2
    return base


def set_contract(world: dict, contract: dict, mode: str) -> dict:
    stored = {
        "morte": bool(contract.get("morte")) if mode == "saga" else False,
        "perfil": contract.get("perfil") if contract.get("perfil") in {"facil", "normal", "brutal"} else world.get("perfil") or "normal",
        "fogoAmigo": bool(contract.get("fogoAmigo")),
        "equipamento": contract.get("equipamento") if contract.get("equipamento") in {"tudo", "sem_magia", "comum"} else "tudo",
        "fuga": True if contract.get("fuga") is None else bool(contract.get("fuga")),
        "travado": True,
    }
    world["contrato"] = stored
    if stored["perfil"]:
        world["perfil"] = stored["perfil"]
    return stored


def bond_effect(level: int) -> str:
    if level >= 3:
        return "vantagem_quando_parceiro_cai"
    if level >= 2:
        return "passar_inspiracao"
    if level >= 1:
        return "ajudar_a_distancia"
    return ""


def raise_bond(world: dict, name: str, scenes: int = 1) -> int:
    bonds = dict(world.get("lacos") or {})
    current = dict(bonds.get(name) or {"nivel": 0, "cenas": 0, "marcos": 0})
    current["cenas"] = int(current.get("cenas") or 0) + scenes
    if current["cenas"] >= 1 and current["nivel"] < 1:
        current["nivel"] = 1
    bonds[name] = current
    world["lacos"] = bonds
    return current["nivel"]


def judgment(character, world: dict, seed: str) -> dict:
    if world.get("julgamentoUsado"):
        return {"ok": False, "linhas": ["O Julgamento desta saga já foi usado."]}
    if world.get("perfil") == "brutal" and not (world.get("contrato") or {}).get("julgamento"):
        world["morto"] = True
        return {"ok": False, "linhas": ["No perfil Brutal o Julgamento está desligado."]}
    rng = roller(seed + "|julgamento")
    passed = 0
    lines = []
    for ability in ("percepcao", "percepcao", "essencia"):
        roll = rng.randint(1, 20)
        bonus = modifier(character.attributes.get(ability, 10))
        total = roll + bonus
        success = total >= 15
        passed += int(success)
        lines.append(f"🎲 Julgamento ({ability}): {roll} + {bonus} = {total} vs CD 15 — {'sucesso' if success else 'falha'}")
    world["julgamentoUsado"] = True
    world["julgamentoDisponivel"] = False
    if passed >= 2:
        world["morto"] = False
        world["vida"] = 1
        world["exaustao"] = min(5, int(world.get("exaustao") or 0) + 1)
        costs = ("cicatriz", "item", "divida")
        world["custoJulgamento"] = costs[roll_die(rng, 3) - 1]
        lines.append(f"Volta com 1 PV, 1 Exaustão e custo: {world['custoJulgamento']}.")
        return {"ok": True, "linhas": lines}
    world["morto"] = True
    world["causaMorte"] = "julgamento"
    lines.append("O Julgamento falhou. Morte permanente.")
    return {"ok": False, "linhas": lines}


def buy(world: dict, item_id: str, seed: str) -> dict:
    item = SHOP.get(item_id)
    if item is None:
        return {"ok": False, "linhas": ["A loja não vende isso."]}
    if not merchant_sells(world) and item_id != "casa":
        return {"ok": False, "linhas": ["Os mercadores legais recusam a venda."]}
    cost = price(world, item["preco"])
    runas = int(world.get("runas") or 0)
    if runas < cost:
        return {"ok": False, "linhas": [f"Faltam Runas ({runas}/{cost})."]}
    if item["colateral"] == "furia" and world.get("elixir"):
        return {"ok": False, "linhas": ["Já há um elixir ativo."]}
    world["runas"] = runas - cost
    lines = [f"Compra: {item['nome']} por {cost} Runas."]
    if item["cura"]:
        count, sides, bonus = item["cura"]
        rng = roller(seed + "|pocao")
        healed = sum(rng.randint(1, sides) for _ in range(count)) + bonus
        world["vida"] = min(int(world.get("vidaMax") or healed), int(world.get("vida") or 0) + healed)
        lines.append(f"Cura {healed}. Vida {world['vida']}/{world['vidaMax']}.")
    if item["colateral"] == "veneno":
        roll = roller(seed + "|veneno").randint(1, 20) + modifier(10)
        if roll < 12:
            cond = list(world.get("condicoes") or [])
            if "envenenado" not in cond:
                cond.append("envenenado")
            world["condicoes"] = cond
            lines.append("O tônico envenena.")
    elif item["colateral"] == "furia":
        world["elixir"] = "furia"
        lines.append("Elixir de Fúria ativo. Conta como fonte de dano extra.")
    elif item["colateral"] == "casa":
        world["casa"] = True
        world["seguro"] = True
        lines.append("A casa é um descanso longo seguro.")
    inventory = list(world.get("inventario") or [])
    if item_id not in {"casa"} and item["nome"] not in inventory:
        inventory.append(item["nome"])
    world["inventario"] = inventory
    return {"ok": True, "linhas": lines}
