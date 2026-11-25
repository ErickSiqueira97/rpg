from app.engine.duel import archetype_profile, fight, profile_from_character
from app.engine.sheet import blank_sheet
from app.simular import simulate
from app.story import Character


def _hero():
    attrs = {"forca": 16, "agilidade": 14, "vigor": 14, "percepcao": 12, "intelecto": 10, "essencia": 10}
    sheet = blank_sheet("espadachim", attrs)
    sheet["nivel"] = 5
    return Character("c", "u", "Lia", "Porto", "Espadachim", "", attrs, sheet)


def test_luta_espelho_e_deterministica():
    hero = _hero()

    def pair():
        left = profile_from_character(hero, 5)
        right = profile_from_character(hero, 5)
        right["nome"] = "Espelho"
        return left, right

    first = fight(*pair(), "semente-fixa")
    second = fight(*pair(), "semente-fixa")
    assert first["linhas"] == second["linhas"]
    left = pair()[0]
    assert first["vencedor"] in {"jogador", "oponente", "empate"}
    tank = archetype_profile("tanque", 5)
    assert tank["ca"] >= left["ca"]


def test_simulador_repete_a_mesma_tabela():
    one = simulate(1, 3, levels=(1,))
    two = simulate(1, 3, levels=(1,))
    assert one == two
    assert len(one) == 19 * 15
    assert all("taxa" in row for row in one)
