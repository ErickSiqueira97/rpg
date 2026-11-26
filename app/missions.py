"""Missões curtas prontas. Sagas longas, em capítulos, entram depois no mesmo registro."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MissionScript:
    id: str
    kind: str  # "missao" (curta) ou, no futuro, "saga"
    title: str
    place: str
    objective: str
    beats: tuple[str, ...]
    span: str
    recommended_level: int | None = None


STARTER = MissionScript(
    id="farol-de-vespera",
    kind="missao",
    title="O sinal do farol",
    place="Porto de Véspera",
    objective=(
        "Descobrir por que o farol apagado de Véspera voltou a acender "
        "e decidir o que fazer com a caixa lacrada de Maíra, sem abri-la."
    ),
    beats=(
        "O protagonista chega ao cais sob a névoa. Maíra espera com uma caixa de madeira marcada por um símbolo.",
        "Dois guardas observam de longe e não interferem, a menos que o protagonista os provoque.",
        "O símbolo da caixa também está riscado num poste do cais e aponta o caminho do farol.",
        "No caminho, um detalhe do passado do farol (quem o apagou, ou por quê) aparece por um NPC ou por um objeto.",
        "Diante do farol, a luz azul pulsa. Dá para entrar, contornar ou chamar alguém.",
        "O desfecho cabe em poucos gestos: entregar a caixa a quem a espera, escondê-la ou confrontar quem reacendeu o farol. A caixa continua lacrada.",
    ),
    span="cerca de 8 turnos",
    recommended_level=1,
)

CATALOG: dict[str, MissionScript] = {STARTER.id: STARTER}


def mission_by_id(script_id: str | None) -> MissionScript | None:
    if not script_id:
        return None
    return CATALOG.get(script_id)


def format_script(mission: MissionScript) -> str:
    steps = "\n".join(f"{index}. {beat}" for index, beat in enumerate(mission.beats, start=1))
    level = f"Nível sugerido: {mission.recommended_level}" if mission.recommended_level else "Nível sugerido: livre"
    kind = "missão curta" if mission.kind == "missao" else "saga"
    return "\n".join(
        [
            f"ROTEIRO ({kind}): {mission.title}",
            f"Lugar: {mission.place}",
            f"Objetivo: {mission.objective}",
            level,
            f"Duração esperada: {mission.span}. Conduza por estes passos e aceite o que o jogador fizer.",
            steps,
            "Quando o objetivo se resolver, encerre a missão com uma cena clara. Não abra a caixa no lugar do jogador.",
        ]
    )


def opening_command(mission: MissionScript | None) -> str:
    if mission is None:
        return (
            "<comando_do_servidor>\n"
            "Abra a cena agora. Apresente o lugar, um NPC e um gancho. Não decida a ação do protagonista.\n"
            "</comando_do_servidor>"
        )
    return (
        "<comando_do_servidor>\n"
        f"Abra a missão «{mission.title}» agora, em {mission.place}. "
        "Mostre o lugar, o objetivo e Maíra com a caixa. Não decida a ação do protagonista. "
        "Siga o roteiro que está no contexto.\n"
        "</comando_do_servidor>"
    )
