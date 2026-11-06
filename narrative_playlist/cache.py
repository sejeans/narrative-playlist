"""가사와 분석 결과를 로컬 JSON에 저장해서 같은 곡을 두 번 처리하지 않게 한다.

나중에 앱으로 갈 때는 이 모듈만 SQLite/DB로 바꾸면 된다.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from . import config


class JsonCache:
    def __init__(self, name: str, cache_dir: Path | None = None):
        self.path = (cache_dir or config.CACHE_DIR) / f"{name}.json"
        self._lock = threading.Lock()
        self._data: dict = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._data = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def __contains__(self, key: str) -> bool:
        return key in self._data
