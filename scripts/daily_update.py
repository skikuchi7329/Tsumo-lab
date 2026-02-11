#!/usr/bin/env python3
"""Tsumo-Lab 日次バッチ処理スクリプト.

毎日深夜に cron 等から実行して以下を自動化する:
  1. 全店舗の最新レポートをスクレイピング → DB 保存
  2. 全店舗の傾向分析を実行 → Markdown レポート出力

使い方:
  # スクレイピング + 分析 (デフォルト)
  python scripts/daily_update.py

  # 分析のみ
  python scripts/daily_update.py --analyze-only

  # スクレイピングのみ
  python scripts/daily_update.py --scrape-only

cron 設定例 (毎日 3:00 に実行):
  0 3 * * * cd /path/to/Tsumo-lab && python scripts/daily_update.py >> logs/cron.log 2>&1
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from utils.logger import setup_logging  # noqa: E402

setup_logging()
logger = logging.getLogger("daily_update")

OUTPUT_DIR = ROOT_DIR / "output"


def run_scrape() -> bool:
    """スクレイピングを実行する.

    Returns:
        成功なら True
    """
    logger.info("=== スクレイピング開始 ===")
    try:
        from main import cmd_scrape

        cmd_scrape()
        logger.info("=== スクレイピング完了 ===")
        return True
    except Exception:
        logger.exception("スクレイピングでエラーが発生しました")
        return False


def run_analyze() -> bool:
    """全店舗分析を実行する.

    Returns:
        成功なら True
    """
    logger.info("=== 分析開始 ===")
    try:
        from main import cmd_analyze

        cmd_analyze(shop_id=None, console=False)
        logger.info("=== 分析完了 ===")
        return True
    except Exception:
        logger.exception("分析でエラーが発生しました")
        return False


def main() -> int:
    """バッチ処理のメインエントリポイント.

    Returns:
        終了コード (0=成功, 1=一部失敗, 2=全失敗)
    """
    parser = argparse.ArgumentParser(
        description="Tsumo-Lab 日次バッチ: スクレイピング + 分析",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="スクレイピングのみ実行",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="分析のみ実行",
    )
    args = parser.parse_args()

    start = datetime.now()
    logger.info(
        "========================================\n"
        "  Tsumo-Lab Daily Update — %s\n"
        "========================================",
        start.strftime("%Y-%m-%d %H:%M:%S"),
    )

    do_scrape = not args.analyze_only
    do_analyze = not args.scrape_only

    results: dict[str, bool] = {}

    if do_scrape:
        results["scrape"] = run_scrape()

    if do_analyze:
        results["analyze"] = run_analyze()

    elapsed = datetime.now() - start
    logger.info(
        "=== バッチ完了: %s (所要時間 %s) ===",
        ", ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in results.items()),
        str(elapsed).split(".")[0],
    )

    if all(results.values()):
        return 0
    elif any(results.values()):
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
