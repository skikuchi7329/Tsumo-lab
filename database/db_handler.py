"""取得済みレポート URL を管理する軽量データベース.

JSON ファイルに取得済み URL と日付を記録し、
重複スクレイピングを防止する。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fetched_urls.json"


class FetchedURLStore:
    """取得済み URL の永続ストア.

    データ構造 (JSON):
        {
            "https://min-repo.com/12345/": {
                "shop_id": "153",
                "date": "2025-06-07",
                "fetched_at": "2025-06-08T10:30:00"
            },
            ...
        }
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self._path = Path(db_path)
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                self._data = json.load(f)
            logger.debug("Loaded %d entries from %s", len(self._data), self._path)
        else:
            self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def is_fetched(self, url: str) -> bool:
        """URL が取得済みかどうかを返す."""
        return url in self._data

    def mark_fetched(self, url: str, shop_id: str, report_date: datetime) -> None:
        """URL を取得済みとして記録する."""
        self._data[url] = {
            "shop_id": shop_id,
            "date": report_date.strftime("%Y-%m-%d"),
            "fetched_at": datetime.now().isoformat(),
        }
        self._save()

    def fetched_count(self) -> int:
        return len(self._data)

    def all_entries(self) -> dict[str, dict[str, Any]]:
        return dict(self._data)
