from app.plans import TRIAL_DAYS, day_key, effective_plan, next_reset_at, trial_ends


def test_teste_dura_sete_dias():
    assert TRIAL_DAYS == 7
    start = 1_700_000_000
    ends = trial_ends(start)
    assert ends - start == 7 * 86400
    assert effective_plan("trial", ends, ends - 1) == "trial"
    assert effective_plan("trial", ends, ends) == "free"
    assert effective_plan("paid", ends, ends + 100) == "paid"
    assert effective_plan("free", ends, start) == "free"


def test_dia_do_jogador_usa_o_fuso():
    # 2024-01-01 01:00 UTC ainda é 31/12 no horário de Brasília (UTC-3).
    moment = 1_704_070_800
    assert day_key(moment, -3) == "2023-12-31"
    assert day_key(moment, 0) == "2024-01-01"
    assert next_reset_at(moment, -3) > moment
