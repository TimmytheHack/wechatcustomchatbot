from __future__ import annotations

import logging

from .connector import ConnectorAdapter


class StubConnector(ConnectorAdapter):
    def __init__(self) -> None:
        self._log = logging.getLogger("connector.stub")

    def send_text(self, chat_id: str, text: str) -> None:
        self._log.info("[stub] send_text chat_id=%s text=%s", chat_id, text)

    def send_gif(self, chat_id: str, gif_path: str) -> None:
        self._log.info("[stub] send_gif chat_id=%s gif_path=%s", chat_id, gif_path)
