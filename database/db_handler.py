"""取得済みレポート URL 管理 + SQLite データ保存.

FetchedURLStore: 取得済み URL を JSON で管理 (重複防止)
SlotDatabase:    SlotData / MachineStats を SQLite に永続保存
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fetched_urls.json"
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "tsumo.db"


# ---------------------------------------------------------------------------
# FetchedURLStore (JSON) — 既存互換
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# SlotDatabase (SQLite) — スロットデータ永続保存
# ---------------------------------------------------------------------------
_SLOT_DATA_DDL = """\
CREATE TABLE IF NOT EXISTS slot_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    shop_id       TEXT    NOT NULL,
    machine_name  TEXT    NOT NULL,
    unit_number   INTEGER NOT NULL,
    g_count       INTEGER NOT NULL DEFAULT 0,
    diff_payout   INTEGER NOT NULL DEFAULT 0,
    bb_count      INTEGER NOT NULL DEFAULT 0,
    rb_count      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(date, shop_id, machine_name, unit_number)
);
"""

_MACHINE_STATS_DDL = """\
CREATE TABLE IF NOT EXISTS machine_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT    NOT NULL,
    shop_id         TEXT    NOT NULL,
    machine_name    TEXT    NOT NULL,
    unit_count      INTEGER NOT NULL DEFAULT 0,
    avg_diff_payout INTEGER NOT NULL DEFAULT 0,
    avg_g_count     INTEGER NOT NULL DEFAULT 0,
    win_rate        REAL    NOT NULL DEFAULT 0.0,
    payout_rate     REAL    NOT NULL DEFAULT 0.0,
    UNIQUE(date, shop_id, machine_name)
);
"""


class SlotDatabase:
    """SQLite によるスロットデータ永続ストア.

    SlotData と MachineStats の両方を管理する。
    UNIQUE 制約で同一データの重複挿入を防止する。
    """

    def __init__(self, db_path: Path | str = DEFAULT_SQLITE_PATH) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(_SLOT_DATA_DDL + _MACHINE_STATS_DDL)

    # -- SlotData ----------------------------------------------------------

    def insert_slot_data(self, records: list[Any]) -> int:
        """SlotData レコードを一括挿入する.

        重複 (同一日・店舗・機種・台番号) は IGNORE する。

        Args:
            records: SlotData のリスト

        Returns:
            挿入された行数
        """
        if not records:
            return 0

        sql = """\
            INSERT OR IGNORE INTO slot_data
                (date, shop_id, machine_name, unit_number,
                 g_count, diff_payout, bb_count, rb_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                r.date.strftime("%Y-%m-%d"),
                r.shop_id,
                r.machine_name,
                r.unit_number,
                r.g_count,
                r.diff_payout,
                r.bb_count,
                r.rb_count,
            )
            for r in records
        ]
        cursor = self._conn.executemany(sql, rows)
        self._conn.commit()
        inserted = cursor.rowcount
        logger.info("Inserted %d slot_data rows (total %d attempted)", inserted, len(records))
        return inserted

    def count_slot_data(self, shop_id: str | None = None, date: str | None = None) -> int:
        """slot_data テーブルの行数を返す."""
        sql = "SELECT COUNT(*) FROM slot_data WHERE 1=1"
        params: list[str] = []
        if shop_id is not None:
            sql += " AND shop_id = ?"
            params.append(shop_id)
        if date is not None:
            sql += " AND date = ?"
            params.append(date)
        row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def fetch_slot_data(
        self,
        shop_id: str | None = None,
        date: str | None = None,
    ) -> list[dict[str, Any]]:
        """slot_data テーブルからレコードを辞書リストで取得する."""
        sql = "SELECT * FROM slot_data WHERE 1=1"
        params: list[str] = []
        if shop_id is not None:
            sql += " AND shop_id = ?"
            params.append(shop_id)
        if date is not None:
            sql += " AND date = ?"
            params.append(date)
        sql += " ORDER BY date, shop_id, machine_name, unit_number"

        cursor = self._conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # -- MachineStats ------------------------------------------------------

    def insert_machine_stats(self, records: list[Any]) -> int:
        """MachineStats レコードを一括挿入する.

        重複 (同一日・店舗・機種) は IGNORE する。

        Args:
            records: MachineStats のリスト

        Returns:
            挿入された行数
        """
        if not records:
            return 0

        sql = """\
            INSERT OR IGNORE INTO machine_stats
                (date, shop_id, machine_name, unit_count,
                 avg_diff_payout, avg_g_count, win_rate, payout_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                r.date.strftime("%Y-%m-%d"),
                r.shop_id,
                r.machine_name,
                r.unit_count,
                r.avg_diff_payout,
                r.avg_g_count,
                r.win_rate,
                r.payout_rate,
            )
            for r in records
        ]
        cursor = self._conn.executemany(sql, rows)
        self._conn.commit()
        inserted = cursor.rowcount
        logger.info("Inserted %d machine_stats rows (total %d attempted)", inserted, len(records))
        return inserted

    def count_machine_stats(self, shop_id: str | None = None, date: str | None = None) -> int:
        """machine_stats テーブルの行数を返す."""
        sql = "SELECT COUNT(*) FROM machine_stats WHERE 1=1"
        params: list[str] = []
        if shop_id is not None:
            sql += " AND shop_id = ?"
            params.append(shop_id)
        if date is not None:
            sql += " AND date = ?"
            params.append(date)
        row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def fetch_machine_stats(
        self,
        shop_id: str | None = None,
        date: str | None = None,
    ) -> list[dict[str, Any]]:
        """machine_stats テーブルからレコードを辞書リストで取得する."""
        sql = "SELECT * FROM machine_stats WHERE 1=1"
        params: list[str] = []
        if shop_id is not None:
            sql += " AND shop_id = ?"
            params.append(shop_id)
        if date is not None:
            sql += " AND date = ?"
            params.append(date)
        sql += " ORDER BY date, shop_id, machine_name"

        cursor = self._conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # -- ユーティリティ ----------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SlotDatabase:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
