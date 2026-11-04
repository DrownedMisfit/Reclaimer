"""Piezas comunes a todos los módulos de IA."""
from __future__ import annotations

from typing import Callable, Optional

# progress(fracción 0..1, texto)   cancelled() -> True si el usuario canceló
ProgressFn = Optional[Callable[[float, str], None]]
CancelFn = Optional[Callable[[], bool]]


class Cancelled(Exception):
    """El usuario canceló la tarea."""


def check_cancel(cancelled: CancelFn) -> None:
    if cancelled and cancelled():
        raise Cancelled()


def report(progress: ProgressFn, frac: float, text: str) -> None:
    if progress:
        progress(max(0.0, min(1.0, frac)), text)
