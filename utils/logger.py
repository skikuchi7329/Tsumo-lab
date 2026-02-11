"""Tsumo-Lab 共通ロガー設定.

ログをコンソール (INFO) とファイル (DEBUG) の両方に出力する。
ファイルログは自動ローテーション (5MB × 3世代) を行う。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# デフォルトのログディレクトリ / ファイル
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "tsumo_lab.log"

# ローテーション設定
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def setup_logging(
    *,
    log_dir: Path | str | None = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> None:
    """アプリケーション共通のロガーを初期化する.

    2回目以降の呼び出しは無視される。

    Args:
        log_dir: ログファイルの出力先ディレクトリ (省略時は <project>/logs/)
        console_level: コンソール出力のログレベル
        file_level: ファイル出力のログレベル
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    log_path = Path(log_dir) / "tsumo_lab.log" if log_dir else _LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 既存ハンドラを除去 (basicConfig との競合回避)
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # --- コンソールハンドラ ---
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # --- ファイルハンドラ (ローテーション) ---
    file_handler = RotatingFileHandler(
        str(log_path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger(__name__).debug(
        "Logging initialized: console=%s, file=%s (%s)",
        logging.getLevelName(console_level),
        logging.getLevelName(file_level),
        log_path,
    )
