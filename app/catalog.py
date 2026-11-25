"""Catálogo jogável. Nomes protegidos ficam só na tabela de apelidos e nunca saem na ficha."""

from __future__ import annotations

import unicodedata

from app.engine.sheet import CLASSES as CLASS_STATS

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
    "espadachim": ["Lâmina Campeã", "Cadências Elementais", "Três Lâminas"],
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

TRAITS = [
    {"id": "forjado_na_luta", "nome": "Forjado na Luta", "beneficio": "+1 no próximo ataque ou salvaguarda depois de falhar, até +3.", "custo": "Começa sem laços."},
    {"id": "sistema", "nome": "Sistema", "beneficio": "Missão diária concede Inspiração Heroica.", "custo": "Falhar a missão diária dá 1 Exaustão."},
    {"id": "olhos_raros", "nome": "Olhos Raros", "beneficio": "Vantagem em Percepção visual. Vê invisíveis a 3 m.", "custo": "Desvantagem contra luz ofuscante."},
    {"id": "dom_singular", "nome": "Dom Singular", "beneficio": "Um poder corporal, como alcance 3 m.", "custo": "Um custo equivalente, como não nadar."},
    {"id": "membro_de_aco", "nome": "Membro de Aço", "beneficio": "Golpe desarmado 1d6.", "custo": "1 natural trava a prótese."},
    {"id": "faro_apurado", "nome": "Faro Apurado", "beneficio": "Vantagem em Percepção e Sobrevivência pelo olfato.", "custo": "Desvantagem contra venenos inalados."},
    {"id": "marca_do_sacrificio", "nome": "Marca do Sacrifício", "beneficio": "Sente criaturas sobrenaturais a 18 m.", "custo": "Encontros extras à noite na saga."},
    {"id": "nulo", "nome": "Nulo", "beneficio": "Vantagem em salvaguardas contra técnicas.", "custo": "Não usa Vias nem itens mágicos."},
    {"id": "divida_com_fera", "nome": "Dívida com Fera", "beneficio": "Uma vez por descanso longo, cai a 1 em vez de 0.", "custo": "Metade das moedas vai para a dívida."},
    {"id": "mutagenico", "nome": "Mutagênico", "beneficio": "Visão no escuro 18 m e Vantagem contra veneno.", "custo": "Desvantagem em Persuasão com pessoas comuns."},
]

# Apelidos só para casar o pedido. A resposta devolve o nome original, nunca o apelido.
_QUERO = [
    (["cacador de sombras", "sobe sozinho", "portais"], "Ascendente Solitário", "humano", "invocador", "Pastor de Sombras", "cacador_de_portais", "grimorio", "sistema"),
    (["anfibio", "correnteza", "ra de sombra"], "Rã-Sombra da Correnteza", "feral", "sombra", "Mestre dos Selos", "aprendiz_de_cla", "folego_interior", ""),
    (["rei faminto", "hospede", "rei das maldições"], "Receptáculo do Rei Faminto", "receptaculo", "exorcista", "Hospedeiro", "estudante_de_exorcismo", "rancor", ""),
    (["punho exorcista", "soca maldições"], "Punho Exorcista", "humano", "punho_de_aura", "Palma Aberta", "estudante_de_exorcismo", "rancor", ""),
    (["barreira", "olhar do infinito"], "Olhar do Infinito", "humano", "desperto", "Dom Singular", "nobre_decadente", "grimorio", "olhos_raros"),
    (["fera selada", "orfao ninja", "selos de mao"], "Herdeiro da Fera Selada", "receptaculo", "sombra", "Mestre dos Selos", "orfao_de_guerra", "folego_interior", ""),
    (["despertar", "artista marcial", "guerreiro do despertar"], "Guerreiro do Despertar", "estelar", "punho_de_aura", "Ascensão", "discipulo_de_eremita", "aura", ""),
    (["elastico", "corpo de borracha", "punho elastico"], "Punho Elástico", "humano", "punho_de_aura", "Palma Aberta", "marujo_errante", "aura", "dom_singular"),
    (["tres laminas", "tres espadas"], "Lâmina Tripla", "humano", "espadachim", "Três Lâminas", "mercenario", "", ""),
    (["colosso", "gigante", "muralha"], "Portador do Colosso", "sangue_de_colosso", "cacador", "Batedor da Muralha", "cadete_da_muralha", "sangue", ""),
    (["anula magia", "antimagia", "antidom"], "Antidom", "humano", "espadachim", "Lâmina Campeã", "orfao_de_guerra", "", "nulo"),
    (["grimorio de vento", "vento"], "Grimorista do Vento", "longevo", "grimorista", "Afinidade Elemental", "orfao_de_guerra", "grimorio", ""),
    (["alquimia", "protese", "aco"], "Alquimista de Aço", "humano", "alquimista", "Alquimista de Combate", "orfao_de_guerra", "transmutacao", "membro_de_aco"),
    (["mare", "lamina da agua", "cadencia"], "Lâmina da Maré", "humano", "espadachim", "Cadências Elementais", "orfao_de_guerra", "folego_interior", "faro_apurado"),
    (["herdeiro do dom", "poder que quebra"], "Herdeiro do Dom", "humano", "punho_de_aura", "Ascensão", "aspirante_a_heroi", "aura", "dom_singular"),
    (["menino da floresta", "exame"], "Menino da Floresta", "humano", "punho_de_aura", "Palma Aberta", "candidato_do_exame", "aura", ""),
    (["raio", "cla assassino"], "Herdeiro do Raio", "humano", "sombra", "Lâmina Silenciosa", "herdeiro_de_cla_assassino", "aura", ""),
    (["serra", "corrente"], "Coração-Serra", "receptaculo", "furioso", "Corpo-Arma", "orfao_de_guerra", "sangue", "divida_com_fera"),
    (["montante", "marca", "espadachim negro"], "Espadachim Negro", "humano", "furioso", "Caminho do Furioso", "mercenario", "", "marca_do_sacrificio"),
    (["guardiao de almas", "lamina que se libera"], "Guardião de Almas", "humano", "espadachim", "Cadências Elementais", "aspirante_a_heroi", "rancor", ""),
    (["cacador mutante", "oleo", "sinais"], "Caçador Mutante", "humano", "cacador", "Caçador da Noite", "discipulo_de_escola_de_caca", "engenho", "mutagenico"),
    (["senhor da noite", "mordida"], "Senhor da Noite", "noturno", "exorcista", "Pacto Abissal", "nobre_decadente", "rancor", ""),
    (["cacador de mortos", "vigia"], "Vigia da Caçada", "humano", "sentinela", "Juramento da Caçada Noturna", "novico_do_templo", "fe", ""),
    (["lua", "lobisomem", "pele de lua"], "Pele de Lua", "licantropo", "furioso", "Fera Interior", "paria_da_floresta", "sangue", ""),
    (["estrela caida", "escudo"], "Estrela Caída", "estelar", "sentinela", "Juramento do Escudo", "criado_no_campo", "fe", ""),
    (["vigilante", "gadgets"], "Vigilante da Noite", "humano", "sombra", "Lâmina Silenciosa", "herdeiro_rico", "engenho", ""),
    (["teia", "aranha", "paredes"], "Saltador de Teias", "feral", "punho_de_aura", "Palma Aberta", "aspirante_a_heroi", "aura", ""),
    (["couraca", "armadura motorizada"], "Couraça de Fogo", "humano", "artifice", "Armadura Motorizada", "herdeiro_rico", "engenho", ""),
    (["gourmet", "cozinheiro", "banquete"], "Gourmet Caçador", "humano", "cozinheiro_de_batalha", "Caçador de Ingredientes", "aprendiz_de_cozinha", "culinaria", ""),
]

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


def suggest_build(text: str) -> dict | None:
    folded = _fold(text)
    if "quero ser" not in folded and "quero jogar" not in folded:
        return None
    best = None
    best_score = 0
    for aliases, nome, raca, classe, sub, origem, via, traco in _QUERO:
        score = sum(1 for alias in aliases if alias in folded)
        if score > best_score:
            best_score = score
            best = {
                "nome": nome,
                "raca": raca,
                "classe": classe,
                "subclasse": sub,
                "origemId": origem,
                "via": via,
                "traco": traco,
            }
    if best is None:
        return {
            "nome": "Andarilho sem trilha",
            "raca": "humano",
            "classe": "espadachim",
            "subclasse": "Lâmina Campeã",
            "origemId": "mercenario",
            "via": "",
            "traco": "",
        }
    return best


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
