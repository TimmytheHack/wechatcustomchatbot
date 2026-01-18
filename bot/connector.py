from __future__ import annotations

from abc import ABC, abstractmethod


class ConnectorAdapter(ABC):
    @abstractmethod
    def send_text(self, chat_id: str, text: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def send_gif(self, chat_id: str, gif_path: str) -> None:
        raise NotImplementedError
