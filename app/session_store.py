"""Хранилище сессий диалога. In-memory по умолчанию, легко заменить на Redis/PG."""
from __future__ import annotations

from typing import Dict

from .bot_logic import DialogState


class SessionStore:
    """Интерфейс хранилища — достаточно реализовать get/reset."""

    def get(self, user_id: int) -> DialogState:  # pragma: no cover
        raise NotImplementedError

    def reset(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """MVP-хранилище: один DialogState на user_id в памяти процесса.

    Замена на Redis/PostgreSQL: реализовать тот же интерфейс
    (get/reset) с (де)сериализацией DialogState — bot_logic.py менять не нужно.
    """

    def __init__(self) -> None:
        self._data: Dict[int, DialogState] = {}

    def get(self, user_id: int) -> DialogState:
        if user_id not in self._data:
            self._data[user_id] = DialogState()
        return self._data[user_id]

    def set(self, user_id: int, state: DialogState) -> None:
        self._data[user_id] = state

    def reset(self, user_id: int) -> None:
        self._data[user_id] = DialogState()

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
