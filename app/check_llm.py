"""Um pedido curto por provedor configurado. Uso: python -m app.check_llm"""

from __future__ import annotations

import asyncio
import time

from app.config import load_dotenv, load_settings
from app.llm import LiteLLMGateway, Attempt, attempts_for, build_spec, message_text, redact


async def probe(settings, attempt: Attempt) -> str:
    gateway = LiteLLMGateway(build_spec(settings), settings)
    response = await gateway._call(
        attempt,
        [{"role": "user", "content": "Responda apenas: ok"}],
        stream=False,
        max_tokens=16,
    )
    return message_text(response).strip() or "(vazio)"


async def run(settings) -> int:
    attempts = attempts_for(settings, "free") + attempts_for(settings, "paid")
    if not attempts:
        print("Nenhum provedor configurado. Defina GEMINI_API_KEY ou outra chave.")
        return 1
    failures = 0
    for attempt in attempts:
        started = time.perf_counter()
        try:
            text = await probe(settings, attempt)
        except Exception as exc:
            failures += 1
            elapsed = time.perf_counter() - started
            detail = redact(str(exc), settings.secrets).replace("\n", " ")
            print(f"erro  {attempt.label}  {attempt.model}  {elapsed:.1f}s  {type(exc).__name__}: {detail[:300]}")
            continue
        elapsed = time.perf_counter() - started
        print(f"ok    {attempt.label}  {attempt.model}  {elapsed:.1f}s  {text[:80]!r}")
    return 1 if failures == len(attempts) else 0


def main() -> None:
    load_dotenv()
    raise SystemExit(asyncio.run(run(load_settings())))


if __name__ == "__main__":
    main()
