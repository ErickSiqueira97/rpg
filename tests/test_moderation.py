from app.moderation import basic_block


def test_bloqueia_conteudo_sexual_com_menor_e_deixa_fantasia_passar():
    assert basic_block("a criança corre pela rua") is False
    assert basic_block("um combate sangrento na ponte") is False
    assert basic_block("criança em cena sexual explícita") is True
    assert basic_block("child porn") is True
    assert basic_block("um mapa", ("mapa secreto",)) is False
    assert basic_block("quero um mapa secreto", ("mapa secreto",)) is True
