"""Limite de narrações simultâneas. Quem não pega vaga logo recebe aviso."""

from __future__ import annotations

import asyncio
import time


class GateFull(Exception):
    pass


class GateTimeout(Exception):
    pass


class Gate:
    def __init__(self, limit: int, max_waiting: int, wait_seconds: float):
        self.limit = max(1, limit)
        self.max_waiting = max(0, max_waiting)
        self.wait_seconds = wait_seconds
        self._active = 0
        self._waiting = 0
        self._cond = asyncio.Condition()

    async def __aenter__(self) -> Gate:
        async with self._cond:
            if self._active >= self.limit and self._waiting >= self.max_waiting:
                raise GateFull()
            self._waiting += 1
            try:
                deadline = time.monotonic() + self.wait_seconds
                while self._active >= self.limit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GateTimeout()
                    try:
                        await asyncio.wait_for(self._cond.wait(), remaining)
                    except TimeoutError as exc:
                        raise GateTimeout() from exc
                self._active += 1
            finally:
                self._waiting -= 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        async with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify(1)
        return False
