"""Catálogo jogável. Nomes protegidos ficam só na tabela de apelidos e nunca saem na ficha."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("uvicorn.error")

from app.engine.sheet import CLASSES as CLASS_STATS, apply_origin_bonus

RACES = [
    {"id": "humano", "nome": "Humano", "papel": "Qualquer", "texto": "Inspiração Heroica a cada descanso longo, +1 perícia e um talento de origem.", "fraqueza": "Sem visão no escuro."},
    {"id": "feral", "nome": "Feral", "papel": "Exploração, Dano", "variantes": ["Lupino", "Felino", "Anfíbio", "Aviano", "Aracnídeo"], "texto": "Ataque natural 1d6 e o movimento da variante.", "fraqueza": "Cada variante tem um ponto fraco."},
    {"id": "rochoso", "nome": "Rochoso", "papel": "Tanque", "texto": "Visão no escuro 36 m, resistência a veneno, +1 PV por nível.", "fraqueza": "Nenhuma extra."},
    {"id": "longevo", "nome": "Longevo", "papel": "Exploração, Controle", "texto": "Visão 18 m, Vantagem contra Enfeitiçado, transe de 4 h.", "fraqueza": "Nenhuma extra."},
    {"id": "miudo", "nome": "Miúdo", "papel": "Controle", "texto": "Pequeno. Vantagem em salvaguardas de Intelecto, Percepção e Essência.", "fraqueza": "Armas pesadas com Desvantagem."},
    {"id": "meio_gigante", "nome": "Meio-Gigante", "papel": "Tanque", "texto": "Fica Grande a partir do nível 5. Vantagem em Força nessa forma.", "fraqueza": "Desvantagem em Furtividade em multidões."},
    {"id": "pequenino", "nome": "Pequenino", "papel": "Exploração, Social", "texto": "Rerrola 1 no d20. Passa por criaturas maiores.", "fraqueza": "Pequeno."},
    {"id": "oni", "nome": "Oni", "papel": "Tanque, Dano", "texto": "Visão 36 m. Uma vez por descanso longo, cai a 1 PV em vez de 0.", "fraqueza": "Nenhuma extra."},
    {"id": "marcado_abissal", "nome": "Marcado Abissal", "papel": "Controle, Social", "texto": "Visão 18 m e legado de técnicas nos níveis 1, 3 e 5.", "fraqueza": "Nenhuma extra."},
    {"id": "sangue_de_dragao", "nome": "Sangue de Dragão", "papel": "Dano", "texto": "Sopro 1d10 e resistência ao tipo escolhido. Voo no nível 5.", "fraqueza": "Nenhuma extra."},
    {"id": "estelar", "nome": "Estelar", "papel": "Dano", "texto": "Ao voltar de 0 PV, Vantagem nos ataques e PV temporários = nível, 1 vez por descanso longo.", "fraqueza": "Sem refeição no descanso longo, não recupera dados de vida."},
    {"id": "noturno", "nome": "Noturno", "papel": "Dano, Social", "texto": "Visão 36 m, resistência a necrótico, mordida que recupera o dano necrótico.", "fraqueza": "Sol direto impõe Desvantagem em ataques e Percepção visual."},
    {"id": "licantropo", "nome": "Licantropo", "papel": "Tanque, Dano", "texto": "Forma lupina com garras e faro.", "fraqueza": "Prata ignora PV temporários. Domínio em PV baixo."},
    {"id": "receptaculo", "nome": "Receptáculo", "papel": "Dano", "texto": "Vantagem contra Enfeitiçado e Amedrontado. Troca com o Hóspede.", "fraqueza": "1 natural na Troca entrega o turno ao Hóspede. 1 Exaustão ao fim."},
    {"id": "sangue_de_colosso", "nome": "Sangue-de-Colosso", "papel": "Tanque", "texto": "Forma Parcial a partir do nível 3: Grande, PV temporários 2 × nível.", "fraqueza": "Desvantagem em Agilidade na forma."},
    {"id": "espirito_amaldicoado", "nome": "Espírito Amaldiçoado", "papel": "Controle", "texto": "Não respira. Resistência a necrótico. Pode amedrontar.", "fraqueza": "Vulnerável a radiante. Cura de fé cura metade."},
    {"id": "automato", "nome": "Autômato", "papel": "Tanque, Suporte", "texto": "Resistência a veneno, descanso longo de 6 h consciente, +1 CA.", "fraqueza": "Medicina não estabiliza."},
    {"id": "iluminado", "nome": "Iluminado", "papel": "Suporte", "texto": "Resistência a radiante e necrótico. Cura 2 × nível, 1 vez por descanso longo.", "fraqueza": "Brilha: Desvantagem em Furtividade até o fim da cena."},
    {"id": "morto_andante", "nome": "Morto-Andante", "papel": "Tanque", "texto": "Salvaguardas contra a morte com Vantagem. Resistência a necrótico e veneno.", "fraqueza": "Cura comum cura metade."},
]

ORIGINS = [
    {"id": "orfao_de_guerra", "nome": "Órfão de Guerra", "atributos": ["agilidade", "vigor", "percepcao"], "talento": "Atacante Selvagem", "pericias": ["atletismo", "sobrevivencia"]},
    {"id": "aprendiz_de_cla", "nome": "Aprendiz de Clã", "atributos": ["agilidade", "intelecto", "percepcao"], "talento": "Alerta", "pericias": ["furtividade", "acrobacia"]},
    {"id": "cadete_da_muralha", "nome": "Cadete da Muralha", "atributos": ["forca", "agilidade", "vigor"], "talento": "Atacante Selvagem", "pericias": ["atletismo", "percepcao"]},
    {"id": "estudante_de_exorcismo", "nome": "Estudante de Exorcismo", "atributos": ["intelecto", "percepcao", "essencia"], "talento": "Iniciado em Magia", "pericias": ["arcano", "intuicao"]},
    {"id": "discipulo_de_eremita", "nome": "Discípulo de Eremita", "atributos": ["forca", "vigor", "percepcao"], "talento": "Habilidoso", "pericias": ["intuicao", "atletismo"]},
    {"id": "aprendiz_de_cozinha", "nome": "Aprendiz de Cozinha", "atributos": ["vigor", "intelecto", "percepcao"], "talento": "Gourmet de Batalha", "pericias": ["sobrevivencia", "medicina"]},
    {"id": "cacador_de_portais", "nome": "Caçador de Portais", "atributos": ["forca", "agilidade", "percepcao"], "talento": "Alerta", "pericias": ["percepcao", "sobrevivencia"]},
    {"id": "candidato_do_exame", "nome": "Candidato do Exame", "atributos": ["agilidade", "vigor", "percepcao"], "talento": "Habilidoso", "pericias": ["sobrevivencia", "natureza"]},
    {"id": "herdeiro_de_cla_assassino", "nome": "Herdeiro de Clã Assassino", "atributos": ["agilidade", "vigor", "intelecto"], "talento": "Alerta", "pericias": ["furtividade", "enganacao"]},
    {"id": "nobre_decadente", "nome": "Nobre Decadente", "atributos": ["intelecto", "percepcao", "essencia"], "talento": "Habilidoso", "pericias": ["historia", "persuasao"]},
    {"id": "aspirante_a_heroi", "nome": "Aspirante a Herói", "atributos": ["forca", "vigor", "essencia"], "talento": "Habilidoso", "pericias": ["atletismo", "persuasao"]},
    {"id": "mercenario", "nome": "Mercenário", "atributos": ["forca", "agilidade", "vigor"], "talento": "Atacante Selvagem", "pericias": ["atletismo", "intimidacao"]},
    {"id": "novico_do_templo", "nome": "Noviço do Templo", "atributos": ["intelecto", "percepcao", "essencia"], "talento": "Iniciado em Magia", "pericias": ["intuicao", "crencas"]},
    {"id": "rato_de_beco", "nome": "Rato de Beco", "atributos": ["agilidade", "vigor", "intelecto"], "talento": "Alerta", "pericias": ["prestidigitacao", "furtividade"]},
    {"id": "erudito", "nome": "Erudito", "atributos": ["vigor", "intelecto", "percepcao"], "talento": "Iniciado em Magia", "pericias": ["arcano", "historia"]},
    {"id": "marujo_errante", "nome": "Marujo Errante", "atributos": ["forca", "agilidade", "essencia"], "talento": "Habilidoso", "pericias": ["atletismo", "percepcao"]},
    {"id": "paria_da_floresta", "nome": "Pária da Floresta", "atributos": ["forca", "vigor", "percepcao"], "talento": "Atacante Selvagem", "pericias": ["sobrevivencia", "adestrar_animais"]},
    {"id": "criado_no_campo", "nome": "Criado no Campo", "atributos": ["forca", "vigor", "essencia"], "talento": "Habilidoso", "pericias": ["atletismo", "adestrar_animais"]},
    {"id": "discipulo_de_escola_de_caca", "nome": "Discípulo de Escola de Caça", "atributos": ["agilidade", "vigor", "percepcao"], "talento": "Alerta", "pericias": ["sobrevivencia", "arcano"]},
    {"id": "herdeiro_rico", "nome": "Herdeiro Rico", "atributos": ["agilidade", "intelecto", "essencia"], "talento": "Habilidoso", "pericias": ["investigacao", "persuasao"]},
]

VIAS = [
    {"id": "folego_interior", "nome": "Fôlego Interior", "atributo": "agilidade", "dano": "cortante", "fraqueza": "Mãos presas: sem selos."},
    {"id": "aura", "nome": "Aura", "atributo": "forca", "dano": "energia", "fraqueza": "Despertar II e III causam Exaustão."},
    {"id": "grimorio", "nome": "Grimório", "atributo": "intelecto", "dano": "fogo", "fraqueza": "Sem o grimório, só truques."},
    {"id": "transmutacao", "nome": "Transmutação", "atributo": "intelecto", "dano": "acido", "fraqueza": "Sem Matéria, o custo sai em PV."},
    {"id": "rancor", "nome": "Rancor", "atributo": "essencia", "dano": "necrotico", "fraqueza": "1 natural causa 1d6 psíquico em si."},
    {"id": "fe", "nome": "Fé", "atributo": "percepcao", "dano": "radiante", "fraqueza": "Quebrar o voto suspende Canalizar."},
    {"id": "engenho", "nome": "Engenho", "atributo": "intelecto", "dano": "perfurante", "fraqueza": "1 natural trava o engenho."},
    {"id": "sangue", "nome": "Sangue", "atributo": "vigor", "dano": "necrotico", "fraqueza": "Perda de controle com PV baixo."},
    {"id": "culinaria", "nome": "Culinária de Batalha", "atributo": "percepcao", "dano": "fogo", "fraqueza": "Precisa de ingredientes."},
]

SUBCLASSES = {
    "espadachim": ["Lâmina Campeã", "Cadências Elementais", "Múltiplas Lâminas"],
    "furioso": ["Caminho do Furioso", "Fera Interior", "Corpo-Arma"],
    "punho_de_aura": ["Palma Aberta", "Rajada de Aura", "Ascensão"],
    "sombra": ["Lâmina Silenciosa", "Mestre dos Selos", "Andarilho da Bruma"],
    "cacador": ["Caçador", "Batedor da Muralha", "Caçador da Noite"],
    "sentinela": ["Juramento da Vigília", "Juramento da Caçada Noturna", "Juramento do Escudo"],
    "exorcista": ["Pacto Abissal", "Técnica Herdada", "Hospedeiro"],
    "grimorista": ["Evocador", "Afinidade Elemental", "Mago de Barreiras"],
    "alquimista": ["Alquimista de Combate", "Alquimista Médico", "Alquimista Proibido"],
    "desperto": ["Sangue Dracônico", "Dom Singular", "Mutante"],
    "invocador": ["Círculo da Terra", "Pastor de Sombras", "Domador de Feras"],
    "devoto": ["Domínio da Vida", "Chama Interior", "Domínio do Selo"],
    "idolo": ["Colégio do Saber", "Palco", "Contador de Lendas"],
    "cozinheiro_de_batalha": ["Caçador de Ingredientes", "Chef de Campanha", "Lâminas de Cozinha"],
    "artifice": ["Armadura Motorizada", "Pistoleiro", "Construtor de Autômatos"],
}
SUBCLASS_RENAME = {"Três Lâminas": "Múltiplas Lâminas", "Tres Laminas": "Múltiplas Lâminas"}

TRAITS = [
    {"id": "forjado_na_luta", "nome": "Forjado na Luta", "beneficio": "+1 no próximo ataque ou salvaguarda depois de falhar, até +3.", "custo": "Começa sem laços.", "efeito_motor": {"acumulo_falha_max": 3}},
    {"id": "sistema", "nome": "Sistema", "beneficio": "Missão diária concede Inspiração Heroica.", "custo": "Falhar a missão diária dá 1 Exaustão.", "efeito_motor": {"missao_diaria": True}},
    {"id": "olhos_raros", "nome": "Olhos Raros", "beneficio": "Vantagem em Percepção visual. Vê invisíveis a 3 m.", "custo": "Desvantagem contra luz ofuscante.", "efeito_motor": {"vantagem_pericia": ["percepcao"]}},
    {"id": "dom_singular", "nome": "Dom Singular", "beneficio": "Um poder corporal, como alcance 3 m.", "custo": "Um custo equivalente, como não nadar.", "efeito_motor": {"alcance_m": 3}},
    {"id": "membro_de_aco", "nome": "Membro de Aço", "beneficio": "Golpe desarmado 1d6.", "custo": "1 natural trava a prótese.", "efeito_motor": {"desarmado_dado": 6, "trava_no_1": True}},
    {"id": "faro_apurado", "nome": "Faro Apurado", "beneficio": "Vantagem em Percepção e Sobrevivência pelo olfato.", "custo": "Desvantagem contra venenos inalados.", "efeito_motor": {"vantagem_pericia": ["percepcao", "sobrevivencia"]}},
    {"id": "marca_do_sacrificio", "nome": "Marca do Sacrifício", "beneficio": "Sente criaturas sobrenaturais a 18 m.", "custo": "Encontros extras à noite na saga.", "efeito_motor": {"sentir_sobrenatural_m": 18}},
    {"id": "nulo", "nome": "Nulo", "beneficio": "Vantagem em salvaguardas contra técnicas.", "custo": "Não usa Vias nem itens mágicos.", "efeito_motor": {"bloqueia_via": True, "vantagem_contra_tecnica": True}},
    {"id": "divida_com_fera", "nome": "Dívida com Fera", "beneficio": "Uma vez por descanso longo, cai a 1 em vez de 0.", "custo": "Metade das moedas vai para a dívida.", "efeito_motor": {"cai_1_pv": True}},
    {"id": "mutagenico", "nome": "Mutagênico", "beneficio": "Visão no escuro 18 m e Vantagem contra veneno.", "custo": "Desvantagem em Persuasão com pessoas comuns.", "efeito_motor": {"desvantagem_pericia": ["persuasao"]}},
]

RACE_EFFECTS = {
    "humano": {"inspiracao_descanso": True},
    "feral": {"ataque_natural": 6, "estagio1_ataque_natural": 8},
    "rochoso": {"pv_por_nivel": 1, "resistencias": ["veneno"]},
    "longevo": {"vantagem_condicao": ["enfeiticado"]},
    "miudo": {"pequeno": True, "salv_vantagem": ["intelecto", "percepcao", "essencia"]},
    "meio_gigante": {"vantagem_forca_nivel": 5},
    "pequenino": {"pequeno": True, "rerola_1": True},
    "oni": {"cai_1_pv": True},
    "marcado_abissal": {"legado_tecnicas": True},
    "sangue_de_dragao": {"resistencias": ["fogo"]},
    "estelar": {"impeto_sobrevivente": True},
    "noturno": {"resistencias": ["necrotico"], "sol_desvantagem": True},
    "licantropo": {"forma_lupina": True},
    "receptaculo": {"vantagem_condicao": ["enfeiticado", "amedrontado"]},
    "sangue_de_colosso": {"forma_parcial_nivel": 3},
    "espirito_amaldicoado": {"resistencias": ["necrotico"], "vulnerabilidades": ["radiante"], "cura_metade": True},
    "automato": {"ca_bonus": 1, "resistencias": ["veneno"]},
    "iluminado": {"resistencias": ["radiante", "necrotico"]},
    "morto_andante": {"vantagem_morte": True, "resistencias": ["necrotico", "veneno"], "cura_metade": True},
}

for _race in RACES:
    _race["efeito_motor"] = RACE_EFFECTS.get(_race["id"], {})

# Apelidos só casam o pedido. Nenhum deles é copiado para nome, conceito ou ficha.
STAGE_LEVELS = (5, 11, 17)

PE_COST = {1: 2, 2: 3, 3: 5, 4: 6, 5: 7}


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def public_catalog() -> dict:
    classes = []
    for class_id, stats in CLASS_STATS.items():
        classes.append(
            {
                "id": class_id,
                "nome": class_id.replace("_", " ").title() if class_id != "punho_de_aura" else "Punho de Aura",
                "dado": f"d{stats['dv']}",
                "salvaguardas": stats["salv"],
                "reserva": stats["reserva"],
                "pericias": stats["pericias"],
                "subclasses": SUBCLASSES[class_id],
            }
        )
    names = {
        "espadachim": "Espadachim",
        "furioso": "Furioso",
        "punho_de_aura": "Punho de Aura",
        "sombra": "Sombra",
        "cacador": "Caçador",
        "sentinela": "Sentinela",
        "exorcista": "Exorcista",
        "grimorista": "Grimorista",
        "alquimista": "Alquimista",
        "desperto": "Desperto",
        "invocador": "Invocador",
        "devoto": "Devoto",
        "idolo": "Ídolo",
        "cozinheiro_de_batalha": "Cozinheiro de Batalha",
        "artifice": "Artífice",
    }
    for item in classes:
        item["nome"] = names[item["id"]]
    return {
        "racas": RACES,
        "origens": ORIGINS,
        "classes": classes,
        "vias": VIAS,
        "tracos": TRAITS,
        "estagios": list(STAGE_LEVELS),
    }


def origin_by_id(origin_id: str) -> dict | None:
    return next((item for item in ORIGINS if item["id"] == origin_id), None)


def rename_subclass(sheet: dict) -> bool:
    renamed = SUBCLASS_RENAME.get(sheet.get("subclasse"))
    if not renamed:
        return False
    sheet["subclasse"] = renamed
    return True


def techniques_for(via_id: str) -> list[dict]:
    via = next((item for item in VIAS if item["id"] == via_id), None)
    if via is None:
        return []
    items = []
    for circle, cost in PE_COST.items():
        items.append(
            {
                "id": f"{via_id}_{circle}",
                "via": via_id,
                "circulo": circle,
                "custo_pe": cost,
                "nome": f"{via['nome']} {circle}",
                "dano": f"{circle + 2}d6",
                "tipo": via["dano"],
                "acao": "acao",
            }
        )
    return items


ARCHETYPE_PATH = Path(__file__).resolve().parent.parent / "data" / "arquetipos.json"
ATTRIBUTES = ("forca", "agilidade", "vigor", "percepcao", "intelecto", "essencia")


def _normalize_name(text: str) -> str:
    folded = _fold(str(text))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def normalize_quero(text: str) -> str:
    normalized = _normalize_name(text)
    normalized = re.sub(r"^(?:quero ser|quero virar|gostaria de ser)\b", "", normalized).strip()
    return re.sub(r"^(?:um|uma|o|a|os|as)\b", "", normalized).strip()


def _load_archetypes() -> tuple[list[dict], dict[str, dict], dict[str, str]]:
    try:
        rows = json.loads(ARCHETYPE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Não foi possível carregar {ARCHETYPE_PATH}.") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("data/arquetipos.json deve conter uma lista de arquétipos.")

    via_ids = {item["id"] for item in VIAS}
    trait_ids = {item["id"] for item in TRAITS}
    by_id: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for row in rows:
        archetype_id = row.get("id")
        if not isinstance(archetype_id, str) or not archetype_id or archetype_id in by_id:
            raise ValueError(f"Id de arquétipo inválido ou duplicado: {archetype_id!r}.")
        race = next((item for item in RACES if item["id"] == row.get("raca")), None)
        origin = origin_by_id(str(row.get("origemId") or ""))
        class_id = row.get("classe")
        if race is None or class_id not in CLASS_STATS or class_id not in SUBCLASSES or origin is None:
            raise ValueError(f"Arquétipo {archetype_id} referencia raça, classe ou origem inválida.")
        if row.get("subclasse") not in SUBCLASSES[class_id]:
            raise ValueError(f"Arquétipo {archetype_id} tem subclasse incompatível.")
        if row.get("via") and row["via"] not in via_ids:
            raise ValueError(f"Arquétipo {archetype_id} tem Via inválida.")
        if row.get("traco") and row["traco"] not in trait_ids:
            raise ValueError(f"Arquétipo {archetype_id} tem traço inválido.")
        if row.get("variante") and row["variante"] not in race.get("variantes", []):
            raise ValueError(f"Arquétipo {archetype_id} tem variante racial inválida.")
        attributes = row.get("atributos")
        if not isinstance(attributes, dict) or set(attributes) != set(ATTRIBUTES):
            raise ValueError(f"Arquétipo {archetype_id} deve conter os seis atributos.")
        if any(type(value) is not int for value in attributes.values()):
            raise ValueError(f"Arquétipo {archetype_id} tem atributos não inteiros.")
        try:
            apply_origin_bonus(attributes, row.get("bonusOrigem"), origin["atributos"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Arquétipo {archetype_id} tem atributos ou bônus de origem inválidos: {exc}") from exc

        by_id[archetype_id] = row
        for alias in (archetype_id, row.get("nome"), *row.get("aliases", [])):
            normalized_alias = _normalize_name(str(alias or ""))
            if not normalized_alias:
                continue
            existing = aliases.get(normalized_alias)
            if existing and existing != archetype_id:
                raise ValueError(
                    f"Apelido ambíguo {normalized_alias!r}: {existing} e {archetype_id}."
                )
            aliases[normalized_alias] = archetype_id
    return rows, by_id, aliases


ARCHETYPES, ARCHETYPES_BY_ID, ARCHETYPE_ALIASES = _load_archetypes()
log.info("arquetipos carregados total=%d", len(ARCHETYPES))


def _build_archetype(archetype_id: str, source: str, reason: str = "") -> dict:
    row = ARCHETYPES_BY_ID[archetype_id]
    return {
        "nome": row["nome"],
        "conceito": row["descricao"],
        "raca": row["raca"],
        "variante": row["variante"],
        "classe": row["classe"],
        "subclasse": row["subclasse"],
        "via": row["via"],
        "origemId": row["origemId"],
        "traco": row["traco"],
        "atributos": dict(row["atributos"]),
        "bonusOrigem": dict(row["bonusOrigem"]),
        "viaSugerida": row["via"],
        "build": row["nome"],
        "buildId": archetype_id,
        "arquetipo_id": archetype_id,
        "fonte": source,
        "motivo": reason,
        "podeCorrigir": True,
    }


def _matching_archetype(normalized: str) -> str | None:
    matches = [
        (alias, archetype_id)
        for alias, archetype_id in ARCHETYPE_ALIASES.items()
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized)
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: len(item[0]), reverse=True)
    return matches[0][1]


def match_known_build(text: str) -> dict | None:
    normalized = normalize_quero(text)
    archetype_id = _matching_archetype(normalized)
    if not archetype_id:
        return None
    return _build_archetype(archetype_id, "apelido")


def suggest_build(text: str) -> dict | None:
    return match_known_build(text)


def _archetype_options() -> list[dict]:
    return [
        {"id": row["id"], "nome": row["nome"], "descricao": row["descricao"]}
        for row in ARCHETYPES
    ]


def _choice_response() -> dict:
    return {"precisaEscolha": True, "opcoes": _archetype_options(), "fonte": "botoes"}


def archetype_choices() -> dict:
    log.info("quero etapa=botoes")
    return _choice_response()


def choose_archetype(archetype_id: str) -> dict | None:
    if archetype_id not in ARCHETYPES_BY_ID:
        return None
    log.info("quero etapa=botoes arquetipo=%s", archetype_id)
    return _build_archetype(archetype_id, "botoes")


def _classifier_messages(normalized: str) -> list[dict[str, str]]:
    ids = ", ".join(ARCHETYPES_BY_ID)
    return [
        {
            "role": "system",
            "content": (
                "Classifique o conceito do jogador em um arquétipo existente. "
                "Não crie ficha nem números. Responda somente JSON válido com as chaves "
                '"arquetipo_id", "confianca" (0 a 1) e "motivo". '
                f"O id deve ser um destes: {ids}. Se não houver boa correspondência, use id vazio e confiança 0."
            ),
        },
        {"role": "user", "content": normalized},
    ]


async def _classify_archetype(gateway, normalized: str, route: str) -> tuple[str, float, str] | None:
    pieces = []
    async for piece in gateway.stream(
        route, _classifier_messages(normalized), expect="json", temperature=0
    ):
        pieces.append(piece)
    text = "".join(getattr(piece, "text", "") for piece in pieces).strip()
    try:
        result = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict):
        return None
    archetype_id = result.get("arquetipo_id")
    confidence = result.get("confianca")
    reason = result.get("motivo")
    if (
        not isinstance(archetype_id, str)
        or archetype_id not in ARCHETYPES_BY_ID
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
        or not isinstance(reason, str)
    ):
        return None
    return archetype_id, float(confidence), reason


async def resolve_quero(text: str, gateway=None, learned_id: str | None = None) -> dict | None:
    normalized = normalize_quero(text)
    if not normalized:
        return None

    matched_id = _matching_archetype(normalized)
    if matched_id:
        log.info("quero etapa=apelido arquetipo=%s", matched_id)
        return _build_archetype(matched_id, "apelido")

    if learned_id in ARCHETYPES_BY_ID:
        log.info("quero etapa=aprendido arquetipo=%s", learned_id)
        return _build_archetype(learned_id, "aprendido")
    if learned_id:
        log.warning("quero aprendizado_invalido arquetipo=%s", learned_id)

    if gateway is not None:
        for attempt, route in ((1, "free"), (2, "fallback")):
            try:
                classified = await _classify_archetype(gateway, normalized, route)
            except Exception:
                log.exception("quero classificador falhou tentativa=%d", attempt)
                classified = None
            if classified and classified[1] >= 0.6:
                archetype_id, confidence, _reason = classified
                log.info(
                    "quero etapa=llm tentativa=%d arquetipo=%s confianca=%.2f",
                    attempt,
                    archetype_id,
                    confidence,
                )
                return _build_archetype(archetype_id, "llm")
            log.warning("quero classificador inconclusivo tentativa=%d", attempt)

    return archetype_choices()

def transformation_offer(race_id: str, class_id: str, level: int, stage: int, subclass: str = "") -> list[dict]:
    """Formas que o nível e o estágio permitem. O motor ainda corta pelo modo."""
    forms = []
    if race_id == "sangue_de_colosso" and level >= 3:
        forms.append({"id": "colosso_parcial", "nome": "Forma Parcial", "grau": "menor", "nivel": 3, "origem": "raca"})
    if race_id == "licantropo" and stage >= 1 and level >= 5:
        forms.append({"id": "licantropo_hibrida", "nome": "Forma Híbrida", "grau": "menor", "nivel": 5, "origem": "raca"})
    if race_id == "licantropo" and stage >= 2 and level >= 11:
        forms.append({"id": "licantropo_total", "nome": "Forma Total", "grau": "maior", "nivel": 11, "origem": "raca"})
    if class_id == "punho_de_aura" and level >= 3:
        forms.append({"id": "despertar_1", "nome": "Despertar I", "grau": "menor", "nivel": 3, "origem": "classe"})
    if class_id == "punho_de_aura" and level >= 11:
        forms.append({"id": "despertar_2", "nome": "Despertar II", "grau": "maior", "nivel": 11, "origem": "classe"})
    if class_id == "punho_de_aura" and subclass == "Ascensão" and level >= 17:
        forms.append({"id": "despertar_3", "nome": "Despertar III", "grau": "suprema", "nivel": 17, "origem": "classe"})
    return forms
