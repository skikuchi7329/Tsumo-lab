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
    _parse_date_from_title,
    _safe_int,
    fetch_report_urls_from_html,
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
