from __future__ import annotations

# Copy this file and implement your own adapter.
# Then update config.yaml with runtime.connector, e.g.:
# runtime:
#   connector: "connectors.my_adapter:MyConnector"

from bot.connector import ConnectorAdapter


class MyConnector(ConnectorAdapter):
    def __init__(self) -> None:
        # Initialize any SDK clients or local hooks here.
        pass

    def send_text(self, chat_id: str, text: str) -> None:
        # Send a text message to WeChat or your bridge.
        raise NotImplementedError

    def send_gif(self, chat_id: str, gif_path: str) -> None:
        # Send a gif (file path) to WeChat or your bridge.
        raise NotImplementedError
