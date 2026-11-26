"""Plano, teste de 7 dias e cota diária. Sem cobrança."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings

TRIAL_DAYS = 7


def trial_ends(start: int, days: int = TRIAL_DAYS) -> int:
    return start + days * 86400


def effective_plan(plan: str, trial_ends_at: int, now: int) -> str:
    """paid permanece. trial vira free quando o prazo acaba."""
    if plan == "paid":
        return "paid"
    if plan == "trial" and now < trial_ends_at:
        return "trial"
    return "free"


def llm_route(plan: str) -> str:
    return "paid" if plan == "paid" else "free"


def daily_limit(plan: str, settings: Settings) -> int | None:
    """None significa sem teto diário."""
    if plan == "paid":
        return None if settings.paid_turns_per_day <= 0 else settings.paid_turns_per_day
    if plan == "trial":
        return settings.trial_turns_per_day
    return settings.free_turns_per_day


def day_key(now: int, offset_hours: int) -> str:
    local = datetime.fromtimestamp(now, timezone.utc) + timedelta(hours=offset_hours)
    return local.date().isoformat()


def next_reset_at(now: int, offset_hours: int) -> int:
    local = datetime.fromtimestamp(now, timezone.utc) + timedelta(hours=offset_hours)
    tomorrow = local.date() + timedelta(days=1)
    midnight_utc = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc)
    return int((midnight_utc - timedelta(hours=offset_hours)).timestamp())


def days_left(trial_ends_at: int, now: int) -> int:
    remaining = trial_ends_at - now
    if remaining <= 0:
        return 0
    return (remaining + 86399) // 86400
