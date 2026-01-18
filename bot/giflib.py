from __future__ import annotations

import random
import re
from pathlib import Path


class GifLibrary:
    def __init__(self, folder: str) -> None:
        self.folder = Path(folder)
        self.index: dict[str, list[Path]] = {}
        self._build_index()

    def _build_index(self) -> None:
        self.index.clear()
        if not self.folder.exists():
            return
        for path in self.folder.glob("*.gif"):
            tags = self._tags_from_name(path.stem)
            for tag in tags:
                self.index.setdefault(tag, []).append(path)

    @staticmethod
    def _tags_from_name(name: str) -> list[str]:
        tokens = re.split(r"[_\-\s]+", name.lower())
        return [token for token in tokens if token]

    def pick_gif(self, tag: str) -> Path | None:
        if not tag:
            return None
        key = tag.lower()
        candidates = self.index.get(key)
        if not candidates:
            return None
        return random.choice(candidates)
