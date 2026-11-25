from app.engine.math import (
    attack_bonus_cap,
    dc_from_label,
    modifier,
    pe_per_turn_cap,
    point_buy_cost,
    proficiency,
    technique_dc_cap,
    validate_point_buy,
)
from app.engine.resolve import apply_death_roll, parse_intent, resolve_action
from app.engine.rng import roll_d20, roller, turn_key
from app.engine.sheet import (
    blank_sheet,
    hp_at_level_one,
    migrate_legacy,
    pe_max,
    training_xp_cap,
)
from app.story import Character


def _hero(attrs=None, classe="espadachim"):
    attrs = attrs or {"forca": 16, "agilidade": 14, "vigor": 14, "percepcao": 10, "intelecto": 10, "essencia": 10}
    sheet = blank_sheet(classe, attrs)
    return Character("c", "u", "Lia", "Porto", classe, "", attrs, sheet)


def test_modificador_e_proficiencia():
    assert modifier(8) == -1
    assert modifier(10) == 0
    assert modifier(14) == 2
    assert modifier(15) == 2
    assert modifier(20) == 5
    assert [proficiency(level) for level in (1, 4, 5, 8, 9, 12, 13, 16, 17, 20)] == [2, 2, 3, 3, 4, 4, 5, 5, 6, 6]


def test_compra_de_pontos_27():
    standard = {"forca": 15, "agilidade": 14, "vigor": 13, "percepcao": 12, "intelecto": 10, "essencia": 8}
    assert point_buy_cost(standard) == 27
    assert validate_point_buy(standard)["forca"] == 15


def test_tetos_de_cd_e_ataque():
    assert dc_from_label("quase_impossivel", mode="missao", profile="normal") == 20
    assert dc_from_label("muito_facil", mode="saga", profile="brutal") == 5
    assert dc_from_label("quase_impossivel", mode="saga", profile="brutal") == 30
    assert dc_from_label("dificil", mode="saga", profile="facil") == 20
    assert attack_bonus_cap(1) == 7
    assert attack_bonus_cap(17) == 14
    assert technique_dc_cap(5) == 17
    assert pe_per_turn_cap(3) == 5
    assert pe_per_turn_cap(11) == 10


def test_migracao_soma_4_e_origem():
    old = {name: 6 for name in ("forca", "agilidade", "vigor", "percepcao", "intelecto", "essencia")}
    attrs, sheet = migrate_legacy(old, "Errante")
    assert attrs["agilidade"] == 10
    assert attrs["forca"] == 11
    assert attrs["vigor"] == 12
    assert sheet["classeId"] == "sombra"
    assert sheet["escala"] == "5e"
    assert sheet["vidaMax"] == hp_at_level_one("sombra", 12)


def test_pv_e_pe():
    assert hp_at_level_one("sentinela", 14) == 12
    pool, kind = pe_max("punho_de_aura", 5, {"agilidade": 16})
    assert kind == "marcial"
    assert pool == 5 + 3
    plena, plena_kind = pe_max("grimorista", 5, {"intelecto": 16})
    assert plena == 27 and plena_kind == "plena"
    assert training_xp_cap(1) == 30


def test_mesma_semente_nao_rerrola():
    rng_a = roller("saga|1|acao")
    rng_b = roller("saga|1|acao")
    assert roll_d20(rng_a, False, False) == roll_d20(rng_b, False, False)
    assert turn_key("s", 1, "ato") == turn_key("s", 1, "ato")
    assert turn_key("s", 1, "ato") != turn_key("s", 2, "ato")


def test_vantagem_e_desvantagem_se_anulam():
    hero = _hero()
    world = {"vida": 20, "vidaMax": 20, "condicoes": ["envenenado"], "morte": {"sucessos": 0, "falhas": 0}}
    intent = parse_intent('{"intencao":"teste","teste":{"tipo":"pericia","pericia":"atletismo","atributo":"forca","dificuldade":"medio","vantagem":"vantagem"}}')
    resolved = resolve_action(
        character=hero, world=world, action="escalo", intent=intent, seed="v1",
        mode="missao", profile="normal", abertura=False, now=0,
    )
    assert resolved["rolagem"]["modo"] == "normal"


def test_20_natural_nao_abre_teste():
    hero = _hero()
    world = {"vida": 12, "vidaMax": 12, "condicoes": [], "morte": {"sucessos": 0, "falhas": 0}, "pericias": []}
    intent = parse_intent('{"teste":{"tipo":"pericia","pericia":"atletismo","dificuldade":"quase_impossivel","vantagem":"nenhuma"}}')
    # Força 16 mod +3, sem proficiência de perícia (espadachim tem atletismo). CD de missão corta em 20.
    resolved = resolve_action(
        character=hero, world=world, action="olho o horizonte", intent=intent, seed="nat",
        mode="missao", profile="normal", abertura=False, now=0,
    )
    assert resolved["rolagem"]["cd"] == 20
    assert "sucesso" in resolved["linhas"][0] or "falha" in resolved["linhas"][0]
    assert "natural" not in resolved["linhas"][0]


def test_salvaguarda_da_morte_missao_e_derrota():
    world = {"vida": 0, "vidaMax": 12, "condicoes": ["inconsciente"], "morte": {"sucessos": 0, "falhas": 2}}
    line = apply_death_roll(world, 8, "missao", "normal")
    assert "falha" in line
    assert world["derrota"] is True
    assert world["vida"] == 1
    assert not world.get("morto")


def test_salvaguarda_da_morte_saga_brutal_mata():
    world = {"vida": 0, "vidaMax": 12, "condicoes": [], "morte": {"sucessos": 0, "falhas": 2}}
    apply_death_roll(world, 1, "saga", "brutal")
    assert world["morto"] is True


def test_vinte_natural_na_morte_volta_com_1():
    world = {"vida": 0, "vidaMax": 12, "condicoes": ["inconsciente", "caido"], "morte": {"sucessos": 2, "falhas": 2}}
    apply_death_roll(world, 20, "saga", "normal")
    assert world["vida"] == 1
    assert "inconsciente" not in world["condicoes"]


def test_descanso_curto_so_um_por_missao_e_pe_pela_metade():
    attrs = {"forca": 10, "agilidade": 16, "vigor": 14, "percepcao": 10, "intelecto": 10, "essencia": 10}
    hero = _hero(attrs, "punho_de_aura")
    world = {"vida": 4, "vidaMax": hero.sheet["vidaMax"], "pe": 0, "peMax": hero.sheet["peMax"], "dadosVida": 1, "condicoes": []}
    first = resolve_action(
        character=hero, world=world, action="faço um descanso curto", intent={"tipo": "nenhum", "intencao": "nenhum"},
        seed="r", mode="missao", profile="normal", abertura=False, now=0,
    )
    assert first["mundo"]["pe"] == hero.sheet["peMax"] // 2
    second = resolve_action(
        character=hero, world=first["mundo"], action="outro descanso curto", intent={"tipo": "nenhum"},
        seed="r2", mode="missao", profile="normal", abertura=False, now=0,
    )
    assert "recusado" in second["linhas"][0]


def test_ataque_escreve_a_linha_no_chat():
    hero = _hero()
    world = {"vida": 12, "vidaMax": 12, "condicoes": [], "morte": {"sucessos": 0, "falhas": 0}, "inimigos": []}
    intent = parse_intent('{"intencao":"atacar","teste":{"tipo":"ataque","atributo":"forca","dificuldade":"medio","vantagem":"nenhuma"}}')
    resolved = resolve_action(
        character=hero, world=world, action="eu ataco o guarda", intent=intent, seed="atk",
        mode="missao", profile="normal", abertura=False, now=0,
    )
    assert resolved["linhas"][0].startswith("⚔️ Ataque")
    assert "vs CA" in resolved["linhas"][0] or "natural" in resolved["linhas"][0]


def test_acao_repetida_nao_rola_de_novo():
    hero = _hero()
    world = {"vida": 12, "vidaMax": 12, "condicoes": [], "morte": {"sucessos": 0, "falhas": 0}}
    intent = {"tipo": "pericia", "pericia": "atletismo", "atributo": "forca", "dificuldade": "quase_impossivel", "vantagem": "nenhuma", "intencao": "teste", "falha": "nenhum", "condicao": ""}
    first = resolve_action(character=hero, world=world, action="escalo o muro", intent=intent, seed="a", mode="missao", profile="normal", abertura=False, now=0)
    if first["rolagem"]["resultado"] != "falha":
        first["rolagem"]["resultado"] = "falha"
        first["mundo"]["ultimaRolagem"] = first["rolagem"]
        first["mundo"]["ultimaAcao"] = "escalo o muro"
    again = resolve_action(character=hero, world=first["mundo"], action="escalo o muro", intent=intent, seed="b", mode="missao", profile="normal", abertura=False, now=0)
    assert "sem nova rolagem" in again["linhas"][0]
