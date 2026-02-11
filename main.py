"""Tsumo-Lab メインスクリプト.

config/config.yaml の全店舗に対して:
  1. タグページからレポート URL を取得
  2. 未取得の URL だけ順次スクレイピング
  3. 取得データを CSV に追記保存
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path

import yaml

from database.db_handler import FetchedURLStore
from models.schema import SlotData, to_dataframe
from scrapers.min_repo_scraper import fetch_report_urls, parse_report_page

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


def run() -> None:
    config = load_config()
    settings = config.get("settings", {})
    interval = settings.get("request_interval_sec", 3)
    user_agent = settings.get("user_agent", "")

    store = FetchedURLStore()

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

        all_records: list[SlotData] = []

        for link in report_links:
            # 取得済みならスキップ
            if store.is_fetched(link.url):
                logger.info("  [SKIP] Already fetched: %s", link.title)
                continue

            logger.info("  [FETCH] %s (%s)", link.title, link.url)

            # Stage 2: レポートページをパース
            try:
                records = parse_report_page(
                    report_url=link.url,
                    report_date=link.date,
                    shop_id=shop_id,
                    user_agent=user_agent,
                )
                all_records.extend(records)
                store.mark_fetched(link.url, shop_id, link.date)
                logger.info("    -> %d records", len(records))
            except Exception:
                logger.exception("    -> Failed to parse: %s", link.url)

            # サーバー負荷軽減 — 3〜5秒のランダム待機
            delay = random.uniform(3.0, 5.0)
            logger.debug("Sleeping %.1f seconds", delay)
            time.sleep(delay)

        # CSV に追記保存
        if all_records:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            csv_path = DATA_DIR / f"{shop_id}_data.csv"
            df = to_dataframe(all_records)

            if csv_path.exists():
                df.to_csv(csv_path, mode="a", header=False, index=False)
            else:
                df.to_csv(csv_path, index=False)
            logger.info("Saved %d records to %s", len(all_records), csv_path)

    logger.info("=== All done ===")


if __name__ == "__main__":
    run()
