"""Tsumo-Lab メインスクリプト.

コマンド:
  scrape   — config/config.yaml の全店舗をスクレイピング → SQLite + CSV 保存
  analyze  — DB 蓄積データから傾向分析 → Markdown レポート出力
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from analysis.trend_analyzer import TrendAnalyzer, generate_report
from database.db_handler import FetchedURLStore, SlotDatabase
from models.schema import MachineStats, SlotData, to_dataframe
from scrapers.min_repo_scraper import (
    fetch_report_urls,
    parse_machine_stats_from_html,
    parse_report_page_from_html,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# scrape コマンド
# ---------------------------------------------------------------------------
def _fetch_html(url: str, user_agent: str) -> str:
    """レポートページの HTML を取得する (1 回の HTTP リクエスト)."""
    import requests

    from scrapers.min_repo_scraper import _create_session

    session = _create_session(user_agent)
    logger.info("Fetching report page: %s", url)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def cmd_scrape() -> None:
    """全店舗をスクレイピングして SQLite + CSV に保存する."""
    config = load_config()
    settings = config.get("settings", {})
    user_agent = settings.get("user_agent", "")

    store = FetchedURLStore()
    db = SlotDatabase()

    try:
        for shop in config.get("shops", []):
            shop_name = shop["name"]
            shop_id = shop["shop_id"]
            tag_name = shop["tag_name"]

            logger.info("=== Processing shop: %s (ID: %s) ===", shop_name, shop_id)

            report_links = fetch_report_urls(
                tag_name=tag_name,
                user_agent=user_agent,
            )
            logger.info("Found %d report links for %s", len(report_links), shop_name)

            all_slot_records: list[SlotData] = []
            all_machine_stats: list[MachineStats] = []

            for link in report_links:
                if store.is_fetched(link.url):
                    logger.info("  [SKIP] Already fetched: %s", link.title)
                    continue

                logger.info("  [FETCH] %s (%s)", link.title, link.url)

                try:
                    html = _fetch_html(link.url, user_agent)

                    slot_records = parse_report_page_from_html(
                        html, link.date, shop_id
                    )
                    machine_stats = parse_machine_stats_from_html(
                        html, link.date, shop_id
                    )

                    db.insert_slot_data(slot_records)
                    db.insert_machine_stats(machine_stats)

                    all_slot_records.extend(slot_records)
                    all_machine_stats.extend(machine_stats)

                    store.mark_fetched(link.url, shop_id, link.date)
                    logger.info(
                        "    -> %d slot records, %d machine stats",
                        len(slot_records),
                        len(machine_stats),
                    )
                except Exception:
                    logger.exception("    -> Failed to parse: %s", link.url)

                delay = random.uniform(3.0, 5.0)
                logger.debug("Sleeping %.1f seconds", delay)
                time.sleep(delay)

            if all_slot_records:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                csv_path = DATA_DIR / f"{shop_id}_data.csv"
                df = to_dataframe(all_slot_records)

                if csv_path.exists():
                    df.to_csv(csv_path, mode="a", header=False, index=False)
                else:
                    df.to_csv(csv_path, index=False)
                logger.info("Saved %d records to %s", len(all_slot_records), csv_path)

        logger.info("=== All done ===")
        logger.info(
            "DB totals: slot_data=%d, machine_stats=%d",
            db.count_slot_data(),
            db.count_machine_stats(),
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# analyze コマンド
# ---------------------------------------------------------------------------
def cmd_analyze(shop_id: str | None = None, console: bool = False) -> None:
    """DB のデータから傾向分析を行い Markdown レポートを出力する.

    Args:
        shop_id: 対象店舗ID (None なら全店舗)
        console: True ならコンソールにも表示
    """
    config = load_config()
    # shop 設定を shop_id → dict でインデックス化
    shop_map: dict[str, dict] = {}
    for s in config.get("shops", []):
        shop_map[s["shop_id"]] = s

    db = SlotDatabase()
    analyzer = TrendAnalyzer(db)

    try:
        if shop_id:
            targets = {shop_id: analyzer.analyze(shop_id)}
        else:
            targets = analyzer.analyze_all_shops()

        if not targets:
            logger.warning("No data to analyze.")
            return

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        for sid, result in targets.items():
            shop_cfg = shop_map.get(sid, {})
            shop_name = shop_cfg.get("name", f"Shop {sid}")
            day_suffix_targets = shop_cfg.get("day_suffix_targets")

            report_md = generate_report(
                result,
                shop_name=shop_name,
                day_suffix_targets=day_suffix_targets,
            )

            # ファイル出力
            today_str = date.today().strftime("%Y%m%d")
            out_path = OUTPUT_DIR / f"report_{sid}_{today_str}.md"
            out_path.write_text(report_md, encoding="utf-8")
            logger.info("Report written to %s", out_path)

            # コンソール出力
            if console:
                print(report_md)
                print()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI エントリポイント
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Tsumo-Lab: パチスロ傾向分析ツール")
    sub = parser.add_subparsers(dest="command")

    # scrape
    sub.add_parser("scrape", help="スクレイピング → DB 保存")

    # analyze
    p_analyze = sub.add_parser("analyze", help="傾向分析 → レポート出力")
    p_analyze.add_argument(
        "--shop-id", default=None, help="対象店舗ID (省略で全店舗)"
    )
    p_analyze.add_argument(
        "--console", action="store_true", help="コンソールにもレポートを表示"
    )

    args = parser.parse_args()

    if args.command == "scrape":
        cmd_scrape()
    elif args.command == "analyze":
        cmd_analyze(shop_id=args.shop_id, console=args.console)
    else:
        # 後方互換: 引数なしは scrape
        cmd_scrape()


if __name__ == "__main__":
    main()
