from app.story import (
    SYSTEM_PROMPT,
    Character,
    NarrativeExtractor,
    StoryMessage,
    apply_patch,
    assemble_context,
    estimate_tokens,
    initial_world,
    parse_narration,
    update_summary,
    validate_attributes,
)

ATTRS = {name: 6 for name in ("forca", "agilidade", "vigor", "percepcao", "intelecto", "essencia")}


def character() -> Character:
    return Character("c1", "u1", "Lia", "Porto de Véspera", "Errante", "procura o farol", dict(ATTRS))


def test_ponto_de_compra():
    assert validate_attributes(dict(ATTRS))["forca"] == 6
    broken = dict(ATTRS)
    broken["forca"] = 10
    try:
        validate_attributes(broken)
    except ValueError as exc:
        assert "12" in str(exc)
    else:
        raise AssertionError("deveria recusar pontos a mais")


def test_resumo_progressivo_corta_o_que_e_antigo():
    summary = ""
    summary = update_summary(summary, "primeiro fato", 500)
    summary = update_summary(summary, "segundo fato", 500)
    assert "primeiro fato" in summary and "segundo fato" in summary
    for index in range(40):
        summary = update_summary(summary, f"fato recente {index}", 40)
    assert "fato recente 39" in summary
    assert "primeiro fato" not in summary
    assert estimate_tokens(summary) <= 80


def test_pacote_e_estavel_e_so_traz_as_ultimas_mensagens():
    recent = []
    for index in range(20):
        role = "player" if index % 2 == 0 else "narrator"
        recent.append(StoryMessage(role, f"mensagem {index}"))
    world = initial_world(character())
    world["npcs"] = [{"nome": "Maíra", "papel": "guia", "disposicao": "fria", "notas": "sabe do farol"}]
    kwargs = dict(
        character=character(),
        world=world,
        summary="- a névoa chegou",
        recent=recent,
        action="<acao_do_jogador>\nEu espero.\n</acao_do_jogador>",
        max_recent=3,
        max_context_tokens=2800,
        summary_max_tokens=450,
        message_max_tokens=180,
    )
    first = assemble_context(**kwargs)
    second = assemble_context(**kwargs)
    assert first.messages == second.messages
    assert first.messages[0]["content"] == SYSTEM_PROMPT
    assert "mestre humano" in SYSTEM_PROMPT
    assert "Maíra" in first.messages[1]["content"]
    assert "a névoa chegou" in first.messages[1]["content"]
    assert len(first.messages) == 6
    assert "mensagem 19" in first.messages[-2]["content"]
    assert "mensagem 0" not in "\n".join(item["content"] for item in first.messages)
    assert first.estimated_tokens == estimate_tokens_of(first.messages)


def estimate_tokens_of(messages):
    from app.story import estimate_messages

    return estimate_messages(messages)


def test_patch_de_mundo_preserva_o_que_nao_mudou():
    world = initial_world(character())
    updated = apply_patch(world, {"quando": "noite", "ganhar": ["lanterna"], "vida": 3})
    assert updated["quando"] == "noite"
    assert "lanterna" in updated["inventario"]
    assert updated["vida"] == 3
    assert updated["lugar"] == world["lugar"]
    assert updated["vidaMax"] == world["vidaMax"]


def test_extrator_esconde_o_estado_e_junta_pedacos():
    extractor = NarrativeExtractor()
    chunks = ["<nar", "rativa>Olá", " mundo</narr", "ativa><estado>{\"beat\":\"x\"}</estado>"]
    prose = "".join(extractor.push(chunk) for chunk in chunks)
    assert prose == "Olá mundo"
    parsed = parse_narration("".join(chunks))
    assert parsed.narrative == "Olá mundo"
    assert parsed.beat == "x"
