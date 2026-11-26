"""Ponto de integração de pagamento. Nenhum gateway está implementado.

Um provedor futuro (Stripe, Mercado Pago, etc.) deve validar o evento
e chamar `apply_billing_event`. O endpoint HTTP responde 501 até lá.
"""

from __future__ import annotations

from app.db import Store

ACTIVATED = "subscription.activated"
CANCELED = "subscription.canceled"


def apply_billing_event(store: Store, user_id: str, event_type: str) -> None:
    if event_type == ACTIVATED:
        store.set_plan(user_id, "paid")
        return
    if event_type == CANCELED:
        store.set_plan(user_id, "free")
        return
    raise ValueError("Evento de cobrança desconhecido.")


WEBHOOK_CONTRACT = {
    "erro": "pagamento_nao_configurado",
    "mensagem": "Nenhum gateway de pagamento está ligado. A história e a cota grátis continuam valendo.",
    "contrato": {
        "type": "subscription.activated | subscription.canceled",
        "userId": "id do jogador",
        "plan": "paid | free",
    },
    "pontoDeIntegracao": "app.billing.apply_billing_event",
}
