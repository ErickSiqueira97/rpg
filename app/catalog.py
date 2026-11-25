"""Catálogo jogável. Nomes protegidos ficam só na tabela de apelidos e nunca saem na ficha."""

from __future__ import annotations

import json
import logging
import re
import unicodedata

log = logging.getLogger("uvicorn.error")

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

# Apelidos só casam o pedido. Nenhum deles é copiado para nome, conceito ou ficha.
_BUILDS = [
    {"id": "ascendente_solitario", "nome": "Ascendente Solitário", "raca": "humano", "variante": "", "classe": "invocador", "subclasse": "Pastor de Sombras", "origemId": "cacador_de_portais", "via": "grimorio", "traco": "sistema", "conceito": "Caçador que sobe sozinho. Ergues sombras de quem derrota e cumpre a tarefa que o próprio corpo impõe.", "aliases": ["solo leveling", "protagonista de solo leveling", "monarca das sombras", "shadow monarch", "sung jinwoo", "jinwoo", "cacador de sombras", "necromante", "necromancer"]},
    {"id": "ra_sombra", "nome": "Rã-Sombra da Correnteza", "raca": "feral", "variante": "Anfíbio", "classe": "sombra", "subclasse": "Mestre dos Selos", "origemId": "aprendiz_de_cla", "via": "folego_interior", "traco": "forjado_na_luta", "conceito": "Anfíbio de um clã das sombras. Luta com selos de água, cópias ilusórias e um passo que some na correnteza.", "aliases": ["greninja", "frog ninja", "sapo ninja", "ninja sapo", "anfibio ninja", "ra de sombra"]},
    {"id": "rei_faminto", "nome": "Receptáculo do Rei Faminto", "raca": "receptaculo", "variante": "", "classe": "exorcista", "subclasse": "Hospedeiro", "origemId": "estudante_de_exorcismo", "via": "rancor", "traco": "divida_com_fera", "conceito": "Estudante que carrega um rei faminto. A troca com o hóspede aumenta o golpe e cobra o corpo depois.", "aliases": ["sukuna", "ryomen", "rei faminto", "rei das maldicoes"]},
    {"id": "punho_exorcista", "nome": "Punho Exorcista", "raca": "humano", "variante": "", "classe": "punho_de_aura", "subclasse": "Palma Aberta", "origemId": "estudante_de_exorcismo", "via": "rancor", "traco": "forjado_na_luta", "conceito": "Estudante que soca maldições de perto. O corpo aguenta o que a energia negativa devolve.", "aliases": ["yuji", "itadori", "punho exorcista"]},
    {"id": "olhar_infinito", "nome": "Olhar do Infinito", "raca": "humano", "variante": "", "classe": "desperto", "subclasse": "Dom Singular", "origemId": "nobre_decadente", "via": "grimorio", "traco": "olhos_raros", "conceito": "Herdeiro de um olhar que vê o que os outros não veem e ergue uma barreira entre si e o golpe.", "aliases": ["gojo", "satoru", "olhar do infinito", "seis olhos", "barreira infinita"]},
    {"id": "fera_selada", "nome": "Herdeiro da Fera Selada", "raca": "receptaculo", "variante": "", "classe": "sombra", "subclasse": "Mestre dos Selos", "origemId": "orfao_de_guerra", "via": "folego_interior", "traco": "forjado_na_luta", "conceito": "Órfão de um clã de selos. Uma fera dorme no corpo e os sinais de mão chamam cópias e vento.", "aliases": ["naruto", "uzumaki", "ninja", "fera selada", "selos de mao", "orfao ninja"]},
    {"id": "guerreiro_despertar", "nome": "Guerreiro do Despertar", "raca": "estelar", "variante": "", "classe": "punho_de_aura", "subclasse": "Ascensão", "origemId": "discipulo_de_eremita", "via": "aura", "traco": "forjado_na_luta", "conceito": "Guerreiro vindo de outro mundo. Treina com um eremita e desperta o corpo em estágios, cada limite rompido mais alto que o anterior.", "aliases": ["goku", "kakaroto", "kakarotto", "saiyajin", "sayajin", "saiyan", "ki fighter", "lutador de ki", "artista marcial de ki", "dragon ball", "artista marcial", "guerreiro do despertar"]},
    {"id": "punho_elastico", "nome": "Punho Elástico", "raca": "humano", "variante": "", "classe": "punho_de_aura", "subclasse": "Palma Aberta", "origemId": "marujo_errante", "via": "aura", "traco": "dom_singular", "conceito": "Marujo cujo corpo estica o golpe até três metros. O mesmo dom o impede de nadar.", "aliases": ["luffy", "punho elastico", "corpo de borracha", "corpo elastico"]},
    {"id": "lamina_tripla", "nome": "Lâmina Tripla", "raca": "humano", "variante": "", "classe": "espadachim", "subclasse": "Três Lâminas", "origemId": "mercenario", "via": "", "traco": "forjado_na_luta", "conceito": "Mercenário que luta com três lâminas ao mesmo tempo e transforma o estilo num ritmo de golpes.", "aliases": ["zoro", "roronoa", "tres laminas", "tres espadas", "swordsman", "espadachim de tres laminas"]},
    {"id": "lamina_dupla", "nome": "Lâmina Dupla", "raca": "humano", "variante": "", "classe": "espadachim", "subclasse": "Três Lâminas", "origemId": "mercenario", "via": "", "traco": "forjado_na_luta", "conceito": "Espadachim de duas mãos. Uma lâmina em cada punho, no estilo leve de quem luta sozinho no claro.", "aliases": ["kirito", "kirigaya", "duas espadas", "duas laminas", "dual wield", "espadachim de duas espadas", "espadachim"]},
    {"id": "portador_colosso", "nome": "Portador do Colosso", "raca": "sangue_de_colosso", "variante": "", "classe": "cacador", "subclasse": "Batedor da Muralha", "origemId": "cadete_da_muralha", "via": "sangue", "traco": "forjado_na_luta", "conceito": "Cadete da muralha que herda um corpo capaz de crescer até a forma colossal.", "aliases": ["eren", "yeager", "jaeger", "portador do colosso", "titã", "tita", "attack on titan"]},
    {"id": "antidom", "nome": "Antidom", "raca": "humano", "variante": "", "classe": "espadachim", "subclasse": "Lâmina Campeã", "origemId": "orfao_de_guerra", "via": "", "traco": "nulo", "conceito": "Órfão cuja lâmina anula técnicas. Não usa Vias: o aço é o bastante.", "aliases": ["asta", "antimagia", "antidom", "anula magia", "nulo"]},
    {"id": "grimorista_vento", "nome": "Grimorista do Vento", "raca": "longevo", "variante": "", "classe": "grimorista", "subclasse": "Afinidade Elemental", "origemId": "orfao_de_guerra", "via": "grimorio", "traco": "olhos_raros", "conceito": "Leitor de um grimório de vento. A página escolhe o elemento e o livro guarda o que a memória não segura.", "aliases": ["yuno", "grimorista de vento", "mago de vento", "sorcerer", "feiticeiro", "mago"]},
    {"id": "alquimista_aco", "nome": "Alquimista de Aço", "raca": "humano", "variante": "", "classe": "alquimista", "subclasse": "Alquimista de Combate", "origemId": "orfao_de_guerra", "via": "transmutacao", "traco": "membro_de_aco", "conceito": "Alquimista de troca equivalente. Uma prótese de aço bate como arma e trava quando o círculo falha.", "aliases": ["edward elric", "elric", "fullmetal", "alquimista", "alchemist", "protese", "membro de aco"]},
    {"id": "lamina_mare", "nome": "Lâmina da Maré", "raca": "humano", "variante": "", "classe": "espadachim", "subclasse": "Cadências Elementais", "origemId": "orfao_de_guerra", "via": "folego_interior", "traco": "faro_apurado", "conceito": "Espadachim de uma cadência de água. O faro acha o rasto e a lâmina segue a maré.", "aliases": ["tanjiro", "kamado", "lamina da mare", "cadencia da agua", "respiracao da agua"]},
    {"id": "herdeiro_dom", "nome": "Herdeiro do Dom", "raca": "humano", "variante": "", "classe": "punho_de_aura", "subclasse": "Ascensão", "origemId": "aspirante_a_heroi", "via": "aura", "traco": "dom_singular", "conceito": "Aspirante que herdou um poder grande demais para o corpo. Cada despertar cobra um recuo em dor.", "aliases": ["deku", "midoriya", "izuku", "herdeiro do dom", "one for all"]},
    {"id": "menino_floresta", "nome": "Menino da Floresta", "raca": "humano", "variante": "", "classe": "punho_de_aura", "subclasse": "Palma Aberta", "origemId": "candidato_do_exame", "via": "aura", "traco": "faro_apurado", "conceito": "Menino da mata que presta um exame de caçadores e solta a aura em rajadas curtas.", "aliases": ["gon freecss", "gon", "menino da floresta", "exame de cacador"]},
    {"id": "herdeiro_raio", "nome": "Herdeiro do Raio", "raca": "humano", "variante": "", "classe": "sombra", "subclasse": "Lâmina Silenciosa", "origemId": "herdeiro_de_cla_assassino", "via": "aura", "traco": "forjado_na_luta", "conceito": "Herdeiro de um clã assassino. O golpe oculto vem com um estalo de raio e some antes do grito.", "aliases": ["killua", "zoldyck", "herdeiro do raio", "cla assassino"]},
    {"id": "coracao_serra", "nome": "Coração-Serra", "raca": "receptaculo", "variante": "", "classe": "furioso", "subclasse": "Corpo-Arma", "origemId": "orfao_de_guerra", "via": "sangue", "traco": "divida_com_fera", "conceito": "Órfão que deve a vida a uma fera-máquina. Lâminas brotam do corpo quando a fúria abre.", "aliases": ["denji", "chainsaw", "coracao serra", "serra humana"]},
    {"id": "espadachim_negro", "nome": "Espadachim Negro", "raca": "humano", "variante": "", "classe": "furioso", "subclasse": "Caminho do Furioso", "origemId": "mercenario", "via": "", "traco": "marca_do_sacrificio", "conceito": "Mercenário de montante marcado. À noite, o que não é deste mundo vem atrás da marca.", "aliases": ["guts", "berserk", "espadachim negro", "marca do sacrificio"]},
    {"id": "guardiao_almas", "nome": "Guardião de Almas", "raca": "humano", "variante": "", "classe": "espadachim", "subclasse": "Cadências Elementais", "origemId": "aspirante_a_heroi", "via": "rancor", "traco": "olhos_raros", "conceito": "Guardião cuja lâmina se libera. O corte carrega o rancor dos que ficaram do outro lado.", "aliases": ["ichigo", "bleach", "guardiao de almas", "lamina que se libera"]},
    {"id": "cacador_mutante", "nome": "Caçador Mutante", "raca": "humano", "variante": "", "classe": "cacador", "subclasse": "Caçador da Noite", "origemId": "discipulo_de_escola_de_caca", "via": "engenho", "traco": "mutagenico", "conceito": "Caçador de uma escola antiga. Óleos, sinais e um corpo mudado pelo veneno que aprendeu a beber.", "aliases": ["geralt", "witcher", "bruxo de rivia", "cacador mutante"]},
    {"id": "senhor_noite", "nome": "Senhor da Noite", "raca": "noturno", "variante": "", "classe": "exorcista", "subclasse": "Pacto Abissal", "origemId": "nobre_decadente", "via": "rancor", "traco": "divida_com_fera", "conceito": "Nobre da noite. A mordida devolve vida e o sol cobra cada passo dado fora da sombra.", "aliases": ["dracula", "alucard", "vampiro", "vampire", "senhor da noite"]},
    {"id": "vigia_cacada", "nome": "Vigia da Caçada", "raca": "humano", "variante": "", "classe": "sentinela", "subclasse": "Juramento da Caçada Noturna", "origemId": "novico_do_templo", "via": "fe", "traco": "forjado_na_luta", "conceito": "Noviço que jurou caçar mortos-vivos. A fé vira luz radiante quando a noite chega.", "aliases": ["van helsing", "helsing", "belmont", "cacador de vampiros", "vigia da cacada"]},
    {"id": "pele_lua", "nome": "Pele de Lua", "raca": "licantropo", "variante": "", "classe": "furioso", "subclasse": "Fera Interior", "origemId": "paria_da_floresta", "via": "sangue", "traco": "forjado_na_luta", "conceito": "Pária da mata. A lua puxa a forma lupina e a fúria mora no mesmo peito.", "aliases": ["lobisomem", "werewolf", "lycan", "pele de lua", "licantropo"]},
    {"id": "estrela_caida", "nome": "Estrela Caída", "raca": "estelar", "variante": "", "classe": "sentinela", "subclasse": "Juramento do Escudo", "origemId": "criado_no_campo", "via": "fe", "traco": "forjado_na_luta", "conceito": "Forasteiro criado no campo. O corpo aguenta o que derrubaria outros e o juramento é pôr-se na frente.", "aliases": ["superman", "clark kent", "estrela caida"]},
    {"id": "vigilante_noite", "nome": "Vigilante da Noite", "raca": "humano", "variante": "", "classe": "sombra", "subclasse": "Lâmina Silenciosa", "origemId": "herdeiro_rico", "via": "engenho", "traco": "forjado_na_luta", "conceito": "Herdeiro rico que desce à noite com engenhos e uma lâmina curta. A fortuna fica no enredo, não no poder.", "aliases": ["batman", "bruce wayne", "vigilante da noite", "vigilante rico"]},
    {"id": "saltador_teias", "nome": "Saltador de Teias", "raca": "feral", "variante": "Aracnídeo", "classe": "punho_de_aura", "subclasse": "Palma Aberta", "origemId": "aspirante_a_heroi", "via": "aura", "traco": "olhos_raros", "conceito": "Aspirante de sangue aracnídeo. Escala paredes, sente o perigo e luta de punhos no alto da rua.", "aliases": ["homem aranha", "spider", "peter parker", "saltador de teias", "aranha"]},
    {"id": "couraca_fogo", "nome": "Couraça de Fogo", "raca": "humano", "variante": "", "classe": "artifice", "subclasse": "Armadura Motorizada", "origemId": "herdeiro_rico", "via": "engenho", "traco": "membro_de_aco", "conceito": "Inventor rico dentro de uma couraça. O engenho dispara e a armadura é o corpo extra.", "aliases": ["homem de ferro", "iron man", "tony stark", "couraca de fogo", "armadura motorizada"]},
    {"id": "gourmet", "nome": "Gourmet Caçador", "raca": "humano", "variante": "", "classe": "cozinheiro_de_batalha", "subclasse": "Caçador de Ingredientes", "origemId": "aprendiz_de_cozinha", "via": "culinaria", "traco": "faro_apurado", "conceito": "Aprendiz de cozinha que caça o ingrediente e serve o banquete antes da luta.", "aliases": ["toriko", "soma", "gourmet", "cozinheiro", "chef"]},
    {"id": "invocador_feras", "nome": "Pastor de Feras", "raca": "humano", "variante": "", "classe": "invocador", "subclasse": "Domador de Feras", "origemId": "paria_da_floresta", "via": "grimorio", "traco": "faro_apurado", "conceito": "Invocador que chama feras para lutar ao lado. O vínculo é o poder, não o golpe próprio.", "aliases": ["summoner", "invocador", "domador de feras"]},
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


def _normalize_request(text: str) -> str:
    folded = _fold(text)
    folded = re.sub(r"^(quero ser|quero jogar)\s+(o|a|os|as|um|uma)\s+", "", folded)
    folded = re.sub(r"^(quero ser|quero jogar)\s+", "", folded)
    return " ".join(folded.split())


def _contains_alias(text: str, alias: str) -> bool:
    """Casa só a frase inteira do apelido, em palavras completas. Sem trecho dentro de outro nome."""
    alias = _fold(alias)
    if len(alias) < 3:
        return False
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) is not None


def _public_from(build: dict, *, fonte: str, motivo: str) -> dict:
    return {
        "nome": build["nome"],
        "conceito": build["conceito"],
        "raca": build["raca"],
        "variante": build.get("variante") or "",
        "classe": build["classe"],
        "subclasse": build["subclasse"],
        "origemId": build["origemId"],
        "via": build.get("via") or "",
        "traco": build.get("traco") or "",
        "build": build["nome"],
        "buildId": build["id"],
        "fonte": fonte,
        "motivo": motivo,
    }


def match_known_build(text: str) -> dict | None:
    remainder = _normalize_request(text)
    if not remainder:
        return None
    hits: list[tuple[int, str, dict]] = []
    for build in _BUILDS:
        for alias in build["aliases"]:
            folded_alias = _fold(alias)
            if _contains_alias(remainder, folded_alias):
                hits.append((len(folded_alias), build["id"], build))
    if not hits:
        return None
    best = max(item[0] for item in hits)
    winners = {item[1]: item[2] for item in hits if item[0] == best}
    if len(winners) != 1:
        log.warning("quero fonte=tabela ambigua builds=%s", ",".join(sorted(winners)))
        return None
    build = next(iter(winners.values()))
    return _public_from(build, fonte="tabela", motivo="apelido inteiro reconhecido na tabela")


def suggest_build(text: str) -> dict | None:
    if not _fold(text).strip():
        return None
    return match_known_build(text)


def _unknown_fallback(motivo: str) -> dict:
    return {
        "nome": "Rastreador sem trilha",
        "conceito": "O pedido não casou com um build conhecido. Esta ficha de explorador é um ponto de partida para ajustar.",
        "raca": "humano",
        "variante": "",
        "classe": "cacador",
        "subclasse": "Caçador",
        "origemId": "paria_da_floresta",
        "via": "",
        "traco": "faro_apurado",
        "build": "",
        "buildId": "",
        "fonte": "fallback",
        "motivo": motivo,
    }


def catalog_prompt() -> str:
    races = "; ".join(
        f"{item['id']} ({item['nome']}: {item['texto']}" + (f"; variantes {', '.join(item['variantes'])}" if item.get("variantes") else "") + ")"
        for item in RACES
    )
    classes = "; ".join(
        f"{item['id']} ({item['nome']}; subclasses: {', '.join(SUBCLASSES[item['id']])})"
        for item in public_catalog()["classes"]
    )
    origins = "; ".join(f"{item['id']} ({item['nome']})" for item in ORIGINS)
    vias = "; ".join(f"{item['id']} ({item['nome']}: {item['fraqueza']})" for item in VIAS)
    traits = "; ".join(f"{item['id']} ({item['nome']}: {item['beneficio']})" for item in TRAITS)
    return (
        "Você monta uma ficha original a partir do pedido. Não copie nome de pessoa, obra ou franquia. "
        "Responda só um JSON com ids deste catálogo.\n"
        f"Raças: {races}\n"
        f"Classes: {classes}\n"
        f"Origens: {origins}\n"
        f"Vias: {vias}\n"
        f"Traços: {traits}\n"
        'Formato: {"nome":"nome original","conceito":"uma ou duas frases","raca":"id","variante":"","classe":"id","subclasse":"nome exato da lista","origemId":"id","via":"id ou vazio","traco":"id"}'
    )


def _blocked_words(text: str) -> list[str]:
    folded = _fold(text)
    found = []
    for build in _BUILDS:
        for alias in build["aliases"]:
            if len(alias) >= 4 and _contains_alias(folded, alias):
                found.append(alias)
    return found


def validate_build(raw: object) -> tuple[dict | None, str]:
    if not isinstance(raw, dict):
        return None, "JSON não é um objeto"
    required = ("nome", "conceito", "raca", "classe", "subclasse", "origemId")
    missing = [key for key in required if not str(raw.get(key) or "").strip()]
    if missing:
        return None, "faltam campos: " + ", ".join(missing)
    race_ids = {item["id"] for item in RACES}
    if raw["raca"] not in race_ids:
        return None, f"raça desconhecida: {raw['raca']}"
    if raw["classe"] not in SUBCLASSES:
        return None, f"classe desconhecida: {raw['classe']}"
    if raw["subclasse"] not in SUBCLASSES[raw["classe"]]:
        return None, f"subclasse desconhecida: {raw['subclasse']}"
    if origin_by_id(str(raw["origemId"])) is None:
        return None, f"origem desconhecida: {raw['origemId']}"
    via = str(raw.get("via") or "")
    if via and via not in {item["id"] for item in VIAS}:
        return None, f"via desconhecida: {via}"
    traco = str(raw.get("traco") or "")
    if traco and traco not in {item["id"] for item in TRAITS}:
        return None, f"traço desconhecido: {traco}"
    race = next(item for item in RACES if item["id"] == raw["raca"])
    variante = str(raw.get("variante") or "")
    if race.get("variantes"):
        if variante not in race["variantes"]:
            return None, "variante inválida para a raça"
    elif variante:
        return None, "essa raça não tem variante"
    nome = " ".join(str(raw["nome"]).split())
    conceito = " ".join(str(raw["conceito"]).split())
    leaked = _blocked_words(nome + " " + conceito)
    if leaked:
        return None, "o texto repete um apelido protegido"
    if raw.get("traco") == "nulo":
        via = ""
    return {
        "nome": nome[:40],
        "conceito": conceito[:400],
        "raca": raw["raca"],
        "variante": variante,
        "classe": raw["classe"],
        "subclasse": raw["subclasse"],
        "origemId": raw["origemId"],
        "via": via,
        "traco": traco,
        "build": "",
        "buildId": "",
        "fonte": "narrador",
        "motivo": "ids válidos do narrador",
    }, ""


def _load_json(raw: str) -> tuple[dict | None, str]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None, "resposta sem JSON"
    try:
        loaded = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None, "JSON inválido"
    return validate_build(loaded)


async def _read_json(gateway, messages) -> str:
    chunks = []
    async for piece in gateway.stream("free", messages, expect="json", temperature=0.2):
        if getattr(piece, "text", ""):
            chunks.append(piece.text)
    return "".join(chunks)


async def resolve_quero(text: str, gateway=None) -> dict | None:
    if not _fold(text).strip():
        return None
    known = match_known_build(text)
    if known:
        log.info("quero fonte=tabela build=%s motivo=%s", known["buildId"], known["motivo"])
        return known
    motivo = "nenhum apelido na tabela"
    if gateway is not None:
        messages = [
            {"role": "system", "content": catalog_prompt()},
            {"role": "user", "content": text},
        ]
        for attempt in (1, 2):
            try:
                raw = await _read_json(gateway, messages)
            except Exception as exc:
                motivo = f"narrador indisponível ({type(exc).__name__})"
                log.warning("quero fonte=narrador tentativa=%s motivo=%s", attempt, motivo)
                break
            parsed, reason = _load_json(raw)
            if parsed:
                log.info("quero fonte=narrador tentativa=%s", attempt)
                return parsed
            motivo = reason or "JSON recusado"
            log.warning("quero fonte=narrador tentativa=%s motivo=%s", attempt, motivo)
            messages.append({"role": "user", "content": "Recusado: " + motivo + ". Responda só o JSON corrigido, com ids do catálogo."})
    fallback = _unknown_fallback(motivo)
    log.warning("quero fonte=fallback motivo=%s", motivo)
    return fallback


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
