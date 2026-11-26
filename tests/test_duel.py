import app.engine.duel as duel
from app.engine.duel import archetype_profile, fight, profile_from_character
from app.engine.sheet import blank_sheet
from app.simular import simulate
from app.story import Character


class _SequenceRoller:
    def __init__(self, values):
        self.values = iter(values)

    def randint(self, _minimum, _maximum):
        return next(self.values)


class _FailingRoller:
    def randint(self, _minimum, _maximum):
        return 1


class _PresetRoller:
    def __init__(self, values):
        self.values = iter(values)

    def randint(self, _minimum, _maximum):
        return next(self.values, 1)


def _defense_rounds(result, fighter_name):
    round_number = 0
    defended = []
    for line in result["linhas"]:
        if line.startswith("── Rodada "):
            round_number = int(line.split()[2])
        elif line.startswith(f"{fighter_name} defende:"):
            defended.append(round_number)
    return defended


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
    outcomes = {"jogador": "Vitória", "oponente": "Derrota", "empate": "Empate"}
    assert first["resultado"] == f"{outcomes[first['vencedor']]} em {first['rodadas']} rodadas."
    assert any(line.startswith("── Rodada 1 ──") for line in first["linhas"])
    assert any("Espelho " in line and " → " in line and " PV" in line for line in first["linhas"])
    tank = archetype_profile("tanque", 5)
    assert tank["ca"] >= left["ca"]


def test_simulador_repete_a_mesma_tabela():
    one = simulate(1, 3, levels=(1,))
    two = simulate(1, 3, levels=(1,))
    assert one == two
    assert len(one) == 19 * 15
    assert all("taxa" in row for row in one)


def test_defesa_concede_dois_pontos_de_ca_contra_ataques():
    attacker = {"nome": "Atacante", "ataque": 5, "classe": "exorcista", "nivel": 1, "raca": "humano", "dado": 6, "mod": 0}
    defender = {"nome": "Defensor", "ca": 14, "vida": 20, "vidaMax": 20, "defesa": True}

    damage, line = duel._strike(_SequenceRoller([10]), attacker, defender, False)

    assert damage == 0
    assert "🎲 10 + 5 = 15 vs CA 16 — erro" in line


def test_ambos_defendem_abaixo_de_um_quarto_no_maximo_a_cada_duas_rodadas(monkeypatch):
    monkeypatch.setattr(duel, "roller", lambda _seed: _FailingRoller())
    left = archetype_profile("dano", 5)
    right = archetype_profile("tanque", 5)
    left["vida"] = left["vidaMax"] // 4 - 1
    right["vida"] = right["vidaMax"] // 4 - 1
    result = fight(left, right, "cooldown")

    assert _defense_rounds(result, "dano") == list(range(1, 41, 2))
    assert _defense_rounds(result, "tanque") == list(range(1, 41, 2))
    assert any("+2 CA contra ataques até seu próximo turno" in line for line in result["linhas"])
    assert any("🎲 1 + " in line and " = " in line for line in result["linhas"])


def test_defesa_nao_ativa_no_limite_de_25_porcento():
    fighter = {"vida": 25, "vidaMax": 100}

    assert not duel._should_defend(fighter, 1, None)


def test_log_mostra_rolagens_de_ataque_e_dano():
    attacker = {"nome": "Atacante", "ataque": 5, "classe": "exorcista", "nivel": 1, "raca": "humano", "dado": 6, "mod": 2}
    defender = {"nome": "Defensor", "ca": 14, "vida": 20, "vidaMax": 20, "defesa": False}

    damage, line = duel._strike(_SequenceRoller([10, 5]), attacker, defender, False)

    assert damage == 7
    assert "🎲 10 + 5 = 15 vs CA 14 — acerto" in line
    assert "🎲 dano 1d6+2 = 7" in line


def test_critico_em_19_exige_subclasse_lamina_campea():
    defender = {"nome": "Defensor", "ca": 10, "vida": 100, "vidaMax": 100, "defesa": False}
    regular = profile_from_character(_hero(), 5)
    champion_character = _hero()
    champion_character.sheet["subclasse"] = "Lâmina Campeã"
    champion = profile_from_character(champion_character, 5)

    assert not regular["criticoAmpliado"]
    assert champion["criticoAmpliado"]
    _damage, regular_line = duel._strike(_SequenceRoller([19, 4]), regular, dict(defender), False)
    _damage, natural_twenty_line = duel._strike(_SequenceRoller([20, 4, 5]), regular, dict(defender), False)
    _damage, champion_line = duel._strike(_SequenceRoller([19, 4, 5]), champion, dict(defender), False)

    assert "— acerto · 🎲 dano 1d10+3 = 7" in regular_line
    assert "— crítico · 🎲 dano 2d10+3 = 12" in natural_twenty_line
    assert "— crítico · 🎲 dano 2d10+3 = 12" in champion_line


def test_iniciativa_soma_agilidade_e_define_quem_age_primeiro(monkeypatch):
    monkeypatch.setattr(duel, "roller", lambda _seed: _PresetRoller([5, 10]))
    player = archetype_profile("dano", 5)
    opponent = archetype_profile("tanque", 5)

    result = fight(player, opponent, "initiative")

    assert result["linhas"][0] == "Iniciativa dano: 🎲 5 + 2 = 7; tanque: 🎲 10 + 0 = 10."
    first_attack = next(line for line in result["linhas"] if line.startswith("⚔️ "))
    assert first_attack.startswith("⚔️ tanque:")
