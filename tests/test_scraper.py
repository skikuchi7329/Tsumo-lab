"""scrapers/min_repo_scraper.py のテスト.

実際のネットワークアクセスなしで、HTML フィクスチャを使って
パース処理の正しさを検証する。
"""

from __future__ import annotations

import textwrap
from datetime import datetime

import pytest

from scrapers.min_repo_scraper import (
    ReportLink,
    _encode_shop_name,
    _extract_shop_part,
    _parse_date_from_title,
    _safe_int,
    fetch_report_urls_from_html,
    filter_links_by_shop,
    parse_machine_stats_from_html,
    parse_report_page_from_html,
)

# =====================================================================
# HTML フィクスチャ
# =====================================================================

# --- タグページ (レポート一覧) のサンプル HTML ---
TAG_PAGE_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja">
    <head><title>レイト荒川沖 データ一覧 – みんレポ</title></head>
    <body>
    <main>
      <article class="post-2883559 post type-post">
        <h2 class="entry-title">
          <a href="https://min-repo.com/2883559/">1/27(火) レイト荒川沖</a>
        </h2>
      </article>
      <article class="post-2588935 post type-post">
        <h2 class="entry-title">
          <a href="https://min-repo.com/2588935/">2025/9/4(木) レイト荒川沖</a>
        </h2>
      </article>
      <article class="post-2406963 post type-post">
        <h2 class="entry-title">
          <a href="https://min-repo.com/2406963/">2025/6/7(土) レイト荒川沖</a>
        </h2>
      </article>
      <article class="post-1702127 post type-post">
        <h2 class="entry-title">
          <a href="https://min-repo.com/1702127/">2024/7/6(土) レイト荒川沖</a>
        </h2>
      </article>
      <article class="post-179336 post type-post">
        <h2 class="entry-title">
          <a href="https://min-repo.com/179336/">2020/7/10(金) 麗都荒川沖</a>
        </h2>
      </article>
    </main>
    </body>
    </html>
""")

# --- レポートページ (個別データ) のサンプル HTML ---
# 2機種 × 各3台のデータを含む
REPORT_PAGE_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja">
    <head><title>2025/6/7(土) レイト荒川沖 – みんレポ</title></head>
    <body>
    <main class="site-main">
    <article>
      <div class="entry-content">

        <h3>マイジャグラーV</h3>
        <table>
          <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
          <tr><td>301</td><td>8,432</td><td>+2,150</td><td>32</td><td>18</td></tr>
          <tr><td>302</td><td>6,218</td><td>-500</td><td>18</td><td>12</td></tr>
          <tr><td>303</td><td>7,891</td><td>+1,800</td><td>28</td><td>21</td></tr>
        </table>

        <h3>ハッピージャグラーVIII</h3>
        <table>
          <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
          <tr><td>501</td><td>5,104</td><td>-1,200</td><td>12</td><td>8</td></tr>
          <tr><td>502</td><td>9,320</td><td>+3,500</td><td>35</td><td>22</td></tr>
          <tr><td>503</td><td>4,560</td><td>-800</td><td>10</td><td>6</td></tr>
        </table>

      </div>
    </article>
    </main>
    </body>
    </html>
""")

# --- ヘッダが異なるパターン (回転数 / BIG / REG 表記) ---
REPORT_PAGE_ALT_HEADERS_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja">
    <head><title>test</title></head>
    <body>
    <h2>アイムジャグラーEX</h2>
    <table>
      <tr><th>台番号</th><th>回転数</th><th>差枚</th><th>BIG</th><th>REG</th></tr>
      <tr><td>101</td><td>7000</td><td>+1000</td><td>25</td><td>15</td></tr>
    </table>
    </body>
    </html>
""")

# --- caption で機種名を指定するパターン ---
REPORT_PAGE_CAPTION_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja">
    <head><title>test</title></head>
    <body>
    <table>
      <caption>ゴーゴージャグラー3</caption>
      <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
      <tr><td>201</td><td>5500</td><td>-300</td><td>15</td><td>10</td></tr>
    </table>
    </body>
    </html>
""")

# --- リンクが article 外にある (フォールバック) パターン ---
TAG_PAGE_FLAT_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html><body>
    <div class="post-list">
      <a href="https://min-repo.com/9999901/">2025/12/1(月) テスト店A</a>
      <a href="https://min-repo.com/9999902/">2025/12/2(火) テスト店A</a>
      <a href="/about/">サイトについて</a>
    </div>
    </body></html>
""")

# --- 機種別サマリーテーブル + 台別テーブルの混在ページ ---
# みんレポのレポートページを再現: 先頭にサマリー、続いて台別データ
REPORT_PAGE_WITH_SUMMARY_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja">
    <head><title>2025/6/7(土) レイト荒川沖 – みんレポ</title></head>
    <body>
    <main class="site-main">
    <article>
      <div class="entry-content">
        <h2>機種別データ</h2>
        <table class="kishu-summary">
          <tr><th>機種</th><th>台数</th><th>平均差枚</th><th>平均G数</th><th>勝率</th><th>出率</th></tr>
          <tr><td>◎ マイジャグラーV</td><td>10</td><td>+1,200</td><td>7,500</td><td>80%</td><td>112.3%</td></tr>
          <tr><td>ハッピージャグラーVIII</td><td>8</td><td>-300</td><td>6,200</td><td>37.5%</td><td>98.5%</td></tr>
          <tr><td>☆ アイムジャグラーEX</td><td>5</td><td>+2,500</td><td>8,100</td><td>100%</td><td>115.0%</td></tr>
          <tr><td>◯ ゴーゴージャグラー3</td><td>3</td><td>+800</td><td>5,500</td><td>66.7%</td><td>107.2%</td></tr>
        </table>

        <h3>マイジャグラーV</h3>
        <table>
          <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
          <tr><td>301</td><td>8,432</td><td>+2,150</td><td>32</td><td>18</td></tr>
          <tr><td>302</td><td>6,218</td><td>-500</td><td>18</td><td>12</td></tr>
          <tr><td>303</td><td>7,891</td><td>+1,800</td><td>28</td><td>21</td></tr>
        </table>

        <h3>ハッピージャグラーVIII</h3>
        <table>
          <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
          <tr><td>501</td><td>5,104</td><td>−1,200</td><td>12</td><td>8</td></tr>
          <tr><td>502</td><td>9,320</td><td>+3,500</td><td>35</td><td>22</td></tr>
          <tr><td>503</td><td>4,560</td><td>-800</td><td>10</td><td>6</td></tr>
        </table>
      </div>
    </article>
    </main>
    </body>
    </html>
""")

# --- 空文字や欠損値を含むテーブル ---
REPORT_PAGE_EMPTY_CELLS_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja"><head><title>test</title></head>
    <body>
    <h3>テスト機種</h3>
    <table>
      <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
      <tr><td>101</td><td></td><td></td><td>5</td><td>3</td></tr>
      <tr><td>102</td><td>3,000</td><td>-</td><td></td><td></td></tr>
      <tr><td>103</td><td>5,000</td><td>+500</td><td>20</td><td>10</td></tr>
    </table>
    </body>
    </html>
""")

# --- 全角数字・全角マイナスを含むテーブル ---
REPORT_PAGE_FULLWIDTH_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja"><head><title>test</title></head>
    <body>
    <h3>全角テスト機種</h3>
    <table>
      <tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>
      <tr><td>２０１</td><td>５，０００</td><td>−１，２００</td><td>１５</td><td>８</td></tr>
    </table>
    </body>
    </html>
""")


# =====================================================================
# _parse_date_from_title
# =====================================================================
class TestParseDateFromTitle:
    def test_full_date(self):
        result = _parse_date_from_title("2025/6/7(土) レイト荒川沖")
        assert result == datetime(2025, 6, 7)

    def test_date_without_year(self):
        result = _parse_date_from_title("1/27(火) レイト荒川沖", fallback_year=2026)
        assert result == datetime(2026, 1, 27)

    def test_date_without_year_defaults_to_current(self):
        result = _parse_date_from_title("3/15(土) 店舗名")
        assert result is not None
        assert result.month == 3
        assert result.day == 15

    def test_no_date(self):
        result = _parse_date_from_title("サイトについて")
        assert result is None


# =====================================================================
# _safe_int
# =====================================================================
class TestSafeInt:
    def test_positive_with_comma(self):
        assert _safe_int("8,432") == 8432

    def test_positive_with_plus(self):
        assert _safe_int("+2,150") == 2150

    def test_negative(self):
        assert _safe_int("-500") == -500

    def test_dash(self):
        assert _safe_int("-") == 0

    def test_empty(self):
        assert _safe_int("") == 0

    def test_plain_number(self):
        assert _safe_int("301") == 301


# =====================================================================
# fetch_report_urls_from_html (Stage 1)
# =====================================================================
class TestFetchReportUrlsFromHtml:
    def test_extract_five_reports(self):
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        assert len(links) == 5

    def test_sorted_by_date_desc(self):
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        dates = [l.date for l in links]
        assert dates == sorted(dates, reverse=True)

    def test_first_link_is_most_recent(self):
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        # "1/27(火)" は年省略 → 今年 (2026) と解釈される
        first = links[0]
        assert first.url == "https://min-repo.com/2883559/"
        assert first.date.month == 1
        assert first.date.day == 27

    def test_urls_are_full(self):
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        for link in links:
            assert link.url.startswith("https://min-repo.com/")

    def test_oldest_link(self):
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        last = links[-1]
        assert last.date == datetime(2020, 7, 10)

    def test_latest_three(self):
        """最新3日分のレポートURLを正しく抜き出せること."""
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        latest_three = links[:3]
        assert len(latest_three) == 3
        # すべて異なる URL
        urls = {l.url for l in latest_three}
        assert len(urls) == 3

    def test_flat_html_fallback(self):
        """article 要素がない場合のフォールバック."""
        links = fetch_report_urls_from_html(TAG_PAGE_FLAT_HTML)
        assert len(links) == 2
        assert links[0].date == datetime(2025, 12, 2)
        assert links[1].date == datetime(2025, 12, 1)


# =====================================================================
# parse_report_page_from_html (Stage 2)
# =====================================================================
class TestParseReportPageFromHtml:
    def test_record_count(self):
        """2機種 × 3台 = 6件のデータが取れること."""
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        assert len(records) == 6

    def test_machine_names(self):
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        names = {r.machine_name for r in records}
        assert "マイジャグラーV" in names
        assert "ハッピージャグラーVIII" in names

    def test_first_record_values(self):
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        r = records[0]
        assert r.unit_number == 301
        assert r.g_count == 8432
        assert r.diff_payout == 2150
        assert r.bb_count == 32
        assert r.rb_count == 18

    def test_negative_diff_payout(self):
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        r302 = [r for r in records if r.unit_number == 302][0]
        assert r302.diff_payout == -500

    def test_shop_id_and_date_propagated(self):
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        for r in records:
            assert r.shop_id == "153"
            assert r.date == datetime(2025, 6, 7)

    def test_alt_headers(self):
        """回転数 / BIG / REG 表記でも正しくパースできること."""
        records = parse_report_page_from_html(
            REPORT_PAGE_ALT_HEADERS_HTML,
            report_date=datetime(2025, 1, 1),
            shop_id="001",
        )
        assert len(records) == 1
        r = records[0]
        assert r.machine_name == "アイムジャグラーEX"
        assert r.unit_number == 101
        assert r.g_count == 7000
        assert r.diff_payout == 1000
        assert r.bb_count == 25
        assert r.rb_count == 15

    def test_caption_machine_name(self):
        """caption タグで機種名を指定しているケース."""
        records = parse_report_page_from_html(
            REPORT_PAGE_CAPTION_HTML,
            report_date=datetime(2025, 1, 1),
            shop_id="001",
        )
        assert len(records) == 1
        assert records[0].machine_name == "ゴーゴージャグラー3"

    def test_empty_page(self):
        """テーブルがないページでは空リストが返ること."""
        html = "<html><body><p>データなし</p></body></html>"
        records = parse_report_page_from_html(
            html, report_date=datetime(2025, 1, 1), shop_id="001"
        )
        assert records == []

    def test_empty_cells_handled(self):
        """空セルが 0 として処理されること."""
        records = parse_report_page_from_html(
            REPORT_PAGE_EMPTY_CELLS_HTML,
            report_date=datetime(2025, 1, 1),
            shop_id="001",
        )
        assert len(records) == 3
        r101 = [r for r in records if r.unit_number == 101][0]
        assert r101.g_count == 0       # 空文字 → 0
        assert r101.diff_payout == 0   # 空文字 → 0
        assert r101.bb_count == 5
        assert r101.rb_count == 3

        r102 = [r for r in records if r.unit_number == 102][0]
        assert r102.g_count == 3000
        assert r102.diff_payout == 0   # "-" → 0
        assert r102.bb_count == 0      # 空文字 → 0
        assert r102.rb_count == 0      # 空文字 → 0

    def test_fullwidth_numbers(self):
        """全角数字・全角マイナスが正しく変換されること."""
        records = parse_report_page_from_html(
            REPORT_PAGE_FULLWIDTH_HTML,
            report_date=datetime(2025, 1, 1),
            shop_id="001",
        )
        assert len(records) == 1
        r = records[0]
        assert r.unit_number == 201
        assert r.g_count == 5000
        assert r.diff_payout == -1200
        assert r.bb_count == 15
        assert r.rb_count == 8

    def test_mixed_page_only_detail_tables(self):
        """サマリー + 台別テーブル混在ページで台別のみ抽出されること."""
        records = parse_report_page_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        # サマリーテーブルはスキップされ、台別テーブルのみ (2機種 × 3台 = 6)
        assert len(records) == 6
        unit_numbers = [r.unit_number for r in records]
        assert 301 in unit_numbers
        assert 502 in unit_numbers


# =====================================================================
# parse_machine_stats_from_html (サマリーテーブルパース)
# =====================================================================
class TestParseMachineStatsFromHtml:
    def test_summary_table_extracted(self):
        """サマリーテーブルから4機種分のデータが取れること."""
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        assert len(stats) == 4

    def test_machine_names_stripped(self):
        """評価記号 (◎☆◯) が機種名から除去されること."""
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        names = {s.machine_name for s in stats}
        assert "マイジャグラーV" in names
        assert "アイムジャグラーEX" in names
        assert "ゴーゴージャグラー3" in names
        # 記号なしも正常
        assert "ハッピージャグラーVIII" in names

    def test_first_stat_values(self):
        """マイジャグラーVの集計値が正しく取れること."""
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        mj = [s for s in stats if s.machine_name == "マイジャグラーV"][0]
        assert mj.unit_count == 10
        assert mj.avg_diff_payout == 1200
        assert mj.avg_g_count == 7500
        assert mj.win_rate == 80.0
        assert mj.payout_rate == 112.3

    def test_negative_avg_diff(self):
        """平均差枚がマイナスの場合."""
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        hj = [s for s in stats if s.machine_name == "ハッピージャグラーVIII"][0]
        assert hj.avg_diff_payout == -300
        assert hj.win_rate == 37.5
        assert hj.payout_rate == 98.5

    def test_shop_id_and_date_propagated(self):
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        for s in stats:
            assert s.shop_id == "153"
            assert s.date == datetime(2025, 6, 7)

    def test_no_summary_table(self):
        """サマリーテーブルがないページでは空リストが返ること."""
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        assert stats == []

    def test_hundred_percent_win_rate(self):
        """勝率100%の機種."""
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        aim = [s for s in stats if s.machine_name == "アイムジャグラーEX"][0]
        assert aim.win_rate == 100.0
        assert aim.payout_rate == 115.0
        assert aim.avg_diff_payout == 2500


# =====================================================================
# FetchedURLStore (database)
# =====================================================================
class TestFetchedURLStore:
    def test_is_fetched_and_mark(self, tmp_path):
        from database.db_handler import FetchedURLStore

        db_path = tmp_path / "test_db.json"
        store = FetchedURLStore(db_path)

        url = "https://min-repo.com/12345/"
        assert not store.is_fetched(url)

        store.mark_fetched(url, shop_id="153", report_date=datetime(2025, 6, 7))
        assert store.is_fetched(url)
        assert store.fetched_count() == 1

    def test_persistence(self, tmp_path):
        db_path = tmp_path / "test_db.json"
        from database.db_handler import FetchedURLStore

        store1 = FetchedURLStore(db_path)
        store1.mark_fetched("https://example.com/1/", "001", datetime(2025, 1, 1))

        # 再読み込み
        store2 = FetchedURLStore(db_path)
        assert store2.is_fetched("https://example.com/1/")


# =====================================================================
# SlotDatabase (SQLite)
# =====================================================================
class TestSlotDatabase:
    def test_insert_and_count_slot_data(self, tmp_path):
        from database.db_handler import SlotDatabase
        from models.schema import SlotData

        db = SlotDatabase(tmp_path / "test.db")
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        inserted = db.insert_slot_data(records)
        assert inserted == 6
        assert db.count_slot_data() == 6
        assert db.count_slot_data(shop_id="153") == 6
        assert db.count_slot_data(date="2025-06-07") == 6
        db.close()

    def test_insert_and_count_machine_stats(self, tmp_path):
        from database.db_handler import SlotDatabase

        db = SlotDatabase(tmp_path / "test.db")
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        inserted = db.insert_machine_stats(stats)
        assert inserted == 4
        assert db.count_machine_stats() == 4
        assert db.count_machine_stats(shop_id="153") == 4
        db.close()

    def test_duplicate_prevention(self, tmp_path):
        """同じデータを2回挿入しても重複しないこと."""
        from database.db_handler import SlotDatabase

        db = SlotDatabase(tmp_path / "test.db")
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        db.insert_slot_data(records)
        db.insert_slot_data(records)  # 2回目
        assert db.count_slot_data() == 6  # 重複しない
        db.close()

    def test_fetch_slot_data(self, tmp_path):
        from database.db_handler import SlotDatabase

        db = SlotDatabase(tmp_path / "test.db")
        records = parse_report_page_from_html(
            REPORT_PAGE_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        db.insert_slot_data(records)
        rows = db.fetch_slot_data(shop_id="153")
        assert len(rows) == 6
        # 各行が辞書であること
        assert "machine_name" in rows[0]
        assert "unit_number" in rows[0]
        assert "diff_payout" in rows[0]
        db.close()

    def test_fetch_machine_stats(self, tmp_path):
        from database.db_handler import SlotDatabase

        db = SlotDatabase(tmp_path / "test.db")
        stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        db.insert_machine_stats(stats)
        rows = db.fetch_machine_stats(shop_id="153")
        assert len(rows) == 4
        assert "machine_name" in rows[0]
        assert "avg_diff_payout" in rows[0]
        assert "win_rate" in rows[0]
        assert "payout_rate" in rows[0]
        db.close()

    def test_context_manager(self, tmp_path):
        from database.db_handler import SlotDatabase

        with SlotDatabase(tmp_path / "test.db") as db:
            records = parse_report_page_from_html(
                REPORT_PAGE_HTML,
                report_date=datetime(2025, 6, 7),
                shop_id="153",
            )
            db.insert_slot_data(records)
            assert db.count_slot_data() == 6


# =====================================================================
# parser_helper
# =====================================================================
class TestParserHelper:
    def test_safe_int_basic(self):
        from utils.parser_helper import safe_int

        assert safe_int("8,432") == 8432
        assert safe_int("+2,150") == 2150
        assert safe_int("-500") == -500
        assert safe_int("") == 0
        assert safe_int("-") == 0
        assert safe_int("301") == 301

    def test_safe_int_fullwidth(self):
        from utils.parser_helper import safe_int

        assert safe_int("５，０００") == 5000
        assert safe_int("−１，２００") == -1200
        assert safe_int("２０１") == 201

    def test_safe_int_default_none(self):
        from utils.parser_helper import safe_int

        assert safe_int("", default=None) is None
        assert safe_int("-", default=None) is None

    def test_safe_float_basic(self):
        from utils.parser_helper import safe_float

        assert safe_float("112.3%") == 112.3
        assert safe_float("80%") == 80.0
        assert safe_float("98.5") == 98.5
        assert safe_float("") == 0.0
        assert safe_float("-") == 0.0

    def test_safe_float_fullwidth(self):
        from utils.parser_helper import safe_float

        assert safe_float("１１２．３％") == 112.3

    def test_strip_rating_symbol(self):
        from utils.parser_helper import strip_rating_symbol

        assert strip_rating_symbol("◎ マイジャグラーV") == "マイジャグラーV"
        assert strip_rating_symbol("☆ アイムジャグラーEX") == "アイムジャグラーEX"
        assert strip_rating_symbol("◯ ゴーゴージャグラー3") == "ゴーゴージャグラー3"
        assert strip_rating_symbol("▲ テスト機種") == "テスト機種"
        assert strip_rating_symbol("ハッピージャグラーVIII") == "ハッピージャグラーVIII"

    def test_safe_int_various_minus_signs(self):
        """各種マイナス記号が正しく処理されること."""
        from utils.parser_helper import safe_int

        # MINUS SIGN (U+2212)
        assert safe_int("\u22121200") == -1200
        # EN DASH (U+2013)
        assert safe_int("\u2013500") == -500
        # FULLWIDTH HYPHEN-MINUS (U+FF0D)
        assert safe_int("\uFF0D800") == -800


# =====================================================================
# 統合テスト: Stage 1 → Stage 2
# =====================================================================
class TestIntegration:
    def test_full_pipeline_with_fixtures(self):
        """タグページから最新3件のURLを取得し、各レポートをパースする統合テスト."""
        # Stage 1
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        latest_three = links[:3]
        assert len(latest_three) == 3

        # Stage 2: 各URLに対して (同じHTMLで代用)
        all_records = []
        for link in latest_three:
            records = parse_report_page_from_html(
                REPORT_PAGE_HTML,
                report_date=link.date,
                shop_id="153",
            )
            all_records.extend(records)

        # 3レポート × 6台 = 18件
        assert len(all_records) == 18

        # 各レポートの日付が正しく伝播している
        dates = {r.date for r in all_records}
        assert len(dates) == 3

    def test_full_pipeline_with_sqlite(self, tmp_path):
        """パース → SQLite 保存 → 読み出しの全フロー."""
        from database.db_handler import SlotDatabase

        db = SlotDatabase(tmp_path / "integration.db")

        # サマリー + 台別の混在ページをパース
        slot_records = parse_report_page_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )
        machine_stats = parse_machine_stats_from_html(
            REPORT_PAGE_WITH_SUMMARY_HTML,
            report_date=datetime(2025, 6, 7),
            shop_id="153",
        )

        # SQLite に保存
        db.insert_slot_data(slot_records)
        db.insert_machine_stats(machine_stats)

        # 検証: slot_data
        assert db.count_slot_data() == 6
        slot_rows = db.fetch_slot_data(shop_id="153", date="2025-06-07")
        assert len(slot_rows) == 6

        # 検証: machine_stats
        assert db.count_machine_stats() == 4
        stat_rows = db.fetch_machine_stats(shop_id="153", date="2025-06-07")
        assert len(stat_rows) == 4

        # 値の正当性を確認
        mj = [r for r in stat_rows if r["machine_name"] == "マイジャグラーV"][0]
        assert mj["avg_diff_payout"] == 1200
        assert mj["avg_g_count"] == 7500
        assert mj["win_rate"] == 80.0
        assert mj["payout_rate"] == 112.3
        assert mj["unit_count"] == 10

        # 台別データの値を確認
        unit301 = [r for r in slot_rows if r["unit_number"] == 301][0]
        assert unit301["g_count"] == 8432
        assert unit301["diff_payout"] == 2150
        assert unit301["machine_name"] == "マイジャグラーV"

        db.close()

    def test_no_data_loss(self, tmp_path):
        """1ページの全データが漏れなくDBに入ること (タスク要件)."""
        from database.db_handler import SlotDatabase

        db = SlotDatabase(tmp_path / "no_loss.db")

        html = REPORT_PAGE_WITH_SUMMARY_HTML
        report_date = datetime(2025, 6, 7)
        shop_id = "153"

        # パース
        slot_records = parse_report_page_from_html(html, report_date, shop_id)
        machine_stats = parse_machine_stats_from_html(html, report_date, shop_id)

        # 保存
        db.insert_slot_data(slot_records)
        db.insert_machine_stats(machine_stats)

        # パース結果と DB の件数が一致すること
        assert db.count_slot_data(shop_id=shop_id) == len(slot_records)
        assert db.count_machine_stats(shop_id=shop_id) == len(machine_stats)

        # 全レコードの値を1件ずつ検証 (DBはソート済みなので unit_number で検索)
        db_slots = db.fetch_slot_data(shop_id=shop_id)
        for rec in slot_records:
            matched = [r for r in db_slots if r["unit_number"] == rec.unit_number]
            assert len(matched) == 1, f"unit_number={rec.unit_number} not found in DB"
            db_row = matched[0]
            assert db_row["g_count"] == rec.g_count
            assert db_row["diff_payout"] == rec.diff_payout
            assert db_row["bb_count"] == rec.bb_count
            assert db_row["rb_count"] == rec.rb_count
            assert db_row["machine_name"] == rec.machine_name

        db_stats = db.fetch_machine_stats(shop_id=shop_id)
        for rec in machine_stats:
            matched = [r for r in db_stats if r["machine_name"] == rec.machine_name]
            assert len(matched) == 1, f"machine={rec.machine_name} not found in DB"
            db_row = matched[0]
            assert db_row["avg_diff_payout"] == rec.avg_diff_payout
            assert db_row["avg_g_count"] == rec.avg_g_count
            assert abs(db_row["win_rate"] - rec.win_rate) < 0.01
            assert abs(db_row["payout_rate"] - rec.payout_rate) < 0.01

        db.close()


# =====================================================================
# filter_links_by_shop (店舗名フィルタ)
# =====================================================================
class TestFilterLinksByShop:
    def _make_links(self) -> list[ReportLink]:
        """実際のみんレポのタグページで見られるパターンを再現."""
        return [
            ReportLink("https://min-repo.com/100/", datetime(2026, 2, 10), "2/10(火)"),
            ReportLink("https://min-repo.com/101/", datetime(2026, 2, 9), "2/9(月)"),
            ReportLink("https://min-repo.com/102/", datetime(2026, 2, 8), "2/8(日) クラウン 大阪府"),
            ReportLink("https://min-repo.com/103/", datetime(2026, 2, 7), "2/7(土) 京都駅前ラッキー"),
            ReportLink("https://min-repo.com/104/", datetime(2026, 2, 7), "2/7(土) 飯田橋プレサス"),
            ReportLink("https://min-repo.com/105/", datetime(2026, 2, 7), "2/7(土)"),
            ReportLink("https://min-repo.com/106/", datetime(2026, 2, 6), "2/6(金)"),
            ReportLink("https://min-repo.com/107/", datetime(2026, 2, 6), "2/6(金) ジール東中島店"),
            ReportLink("https://min-repo.com/108/", datetime(2025, 6, 7), "2025/6/7(土) レイト荒川沖"),
        ]

    def test_filter_removes_other_shops(self):
        """他店舗のレポートが除外されること."""
        links = self._make_links()
        filtered = filter_links_by_shop(links, ["麗都荒川沖", "レイト荒川沖"])
        titles = [l.title for l in filtered]

        # 日付のみ (店名なし) → 通過
        assert "2/10(火)" in titles
        assert "2/9(月)" in titles
        assert "2/7(土)" in titles
        assert "2/6(金)" in titles

        # キーワード一致 → 通過
        assert "2025/6/7(土) レイト荒川沖" in titles

        # 他店舗 → 除外
        assert "2/8(日) クラウン 大阪府" not in titles
        assert "2/7(土) 京都駅前ラッキー" not in titles
        assert "2/7(土) 飯田橋プレサス" not in titles
        assert "2/6(金) ジール東中島店" not in titles

    def test_filter_count(self):
        links = self._make_links()
        filtered = filter_links_by_shop(links, ["麗都荒川沖", "レイト荒川沖"])
        assert len(filtered) == 5  # 日付のみ4件 + レイト荒川沖1件

    def test_no_keywords_returns_all(self):
        """title_keywords が None なら全件返す."""
        links = self._make_links()
        filtered = filter_links_by_shop(links, None)
        assert len(filtered) == len(links)

    def test_empty_keywords_returns_all(self):
        """title_keywords が空リストなら全件返す."""
        links = self._make_links()
        filtered = filter_links_by_shop(links, [])
        assert len(filtered) == len(links)


class TestExtractShopPart:
    def test_date_only(self):
        assert _extract_shop_part("2/10(火)") == ""

    def test_with_shop_name(self):
        assert _extract_shop_part("2/8(日) クラウン 大阪府") == "クラウン 大阪府"

    def test_full_date_with_shop(self):
        assert _extract_shop_part("2025/6/7(土) レイト荒川沖") == "レイト荒川沖"

    def test_full_date_without_shop(self):
        assert _extract_shop_part("2025/6/7(土)") == ""


# =====================================================================
# _encode_shop_name (店舗名 → URL エンコード)
# =====================================================================
class TestEncodeShopName:
    def test_japanese_name_encoded(self):
        """日本語の店舗名が URL エンコードされること."""
        result = _encode_shop_name("麗都荒川沖")
        assert result == "%E9%BA%97%E9%83%BD%E8%8D%92%E5%B7%9D%E6%B2%96"

    def test_already_encoded_passthrough(self):
        """既にエンコード済みの文字列はそのまま返ること."""
        encoded = "%E9%BA%97%E9%83%BD%E8%8D%92%E5%B7%9D%E6%B2%96"
        assert _encode_shop_name(encoded) == encoded

    def test_ascii_name(self):
        """ASCII のみの名前はそのまま返ること."""
        assert _encode_shop_name("TestShop") == "TestShop"

    def test_mixed_name(self):
        """日本語 + ASCII 混在の店舗名もエンコードされること."""
        result = _encode_shop_name("SLOT館A")
        # 日本語部分がエンコードされ、ASCII はそのまま
        assert "SLOT" in result
        assert "A" in result
