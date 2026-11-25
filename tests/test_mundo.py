from app.engine.combat import apply_resistance, attack_count, cover_bonus, opportunity
from app.engine.resolve import resolve_action
from app.engine.sheet import blank_sheet
from app.engine.world import add_stars, buy, merchant_sells, notice_crime, price
from app.story import Character


def _hero():
    attrs = {"forca": 16, "agilidade": 14, "vigor": 14, "percepcao": 10, "intelecto": 10, "essencia": 10}
    return Character("c", "u", "Lia", "Porto", "Espadachim", "", attrs, blank_sheet("espadachim", attrs))


def test_zonas_cobertura_resistencia_e_teto_de_ataques():
    assert opportunity("corpo", "longe", False) is True
    assert opportunity("corpo", "longe", True) is False
    assert cover_bonus("meia") == 2
    assert cover_bonus("total") is None
    assert apply_resistance(9, "cortante", {"resistencias": ["cortante"]}) == 4
    assert apply_resistance(9, "fogo", {"imunidades": ["fogo"]}) == 0
    assert apply_resistance(9, "frio", {"vulnerabilidades": ["frio"]}) == 18
    assert attack_count(4, 2) == 5
    assert attack_count(4, 0, surge=True) == 8


def test_furto_visto_sobe_estrela_e_preco():
    assert notice_crime("s", 10, [12]) is True
    world = {"procurado": 0, "testemunhas": [12]}
    assert add_stars(world, "furto", True) == 1
    world["procurado"] = 4
    assert price(world, 50) == 100
    world["procurado"] = 3
    assert merchant_sells(world) is False


def test_loja_nao_vende_sem_runas_e_cura_com_runas():
    hero = _hero()
    world = {"vida": 4, "vidaMax": 20, "runas": 0, "inventario": []}
    poor = buy(world, "pocao_cura", "semente")
    assert poor["ok"] is False
    world["runas"] = 50
    bought = buy(world, "pocao_cura", "semente")
    assert bought["ok"] is True
    assert world["vida"] > 4
    assert world["runas"] == 0


def test_acao_de_furto_grava_procurado():
    hero = _hero()
    world = {"vida": 12, "vidaMax": 12, "condicoes": [], "testemunhas": [15]}
    resolved = resolve_action(
        character=hero, world=world, action="eu cometo um furto no cais",
        intent={"tipo": "nenhum", "intencao": "nenhum"}, seed="crime",
        mode="missao", profile="normal", abertura=False, now=0,
    )
    assert resolved["mundo"]["procurado"] == 1
