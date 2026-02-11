"""Tsumo-Lab メインスクリプト.

config/config.yaml の全店舗に対して:
  1. タグページからレポート URL を取得
  2. 未取得の URL だけ順次スクレイピング
  3. 台別データ (SlotData) + 機種別集計 (MachineStats) を SQLite に保存
  4. CSV にも追記保存 (従来互換)
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path

import yaml

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


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fetch_html(url: str, user_agent: str) -> str:
    """レポートページの HTML を取得する (1 回の HTTP リクエスト)."""
    import requests

    from scrapers.min_repo_scraper import _create_session

    session = _create_session(user_agent)
    logger.info("Fetching report page: %s", url)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def run() -> None:
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

            # Stage 1: タグページからレポート URL を取得
            report_links = fetch_report_urls(
                tag_name=tag_name,
                user_agent=user_agent,
            )
            logger.info("Found %d report links for %s", len(report_links), shop_name)

            all_slot_records: list[SlotData] = []
            all_machine_stats: list[MachineStats] = []

            for link in report_links:
                # 取得済みならスキップ
                if store.is_fetched(link.url):
                    logger.info("  [SKIP] Already fetched: %s", link.title)
                    continue

                logger.info("  [FETCH] %s (%s)", link.title, link.url)

                # Stage 2: レポートページをパース (1 回の HTTP で両方抽出)
                try:
                    html = _fetch_html(link.url, user_agent)

                    slot_records = parse_report_page_from_html(
                        html, link.date, shop_id
                    )
                    machine_stats = parse_machine_stats_from_html(
                        html, link.date, shop_id
                    )

                    # SQLite に保存
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

                # サーバー負荷軽減 — 3〜5秒のランダム待機
                delay = random.uniform(3.0, 5.0)
                logger.debug("Sleeping %.1f seconds", delay)
                time.sleep(delay)

            # CSV に追記保存 (従来互換)
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


if __name__ == "__main__":
    run()
