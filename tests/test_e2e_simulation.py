"""最終動作シミュレーション: レイト荒川沖 (shop_id=153).

実際のネットワーク接続なしに、一気通貫で以下のフローを検証:
  タグページパース → レポートページパース → DB保存 → 分析 → レポート出力

複数日分のリアルなHTMLフィクスチャを使い、
データの整合性・レポートの完全性を確認する。
"""

from __future__ import annotations

import textwrap
from datetime import date, datetime
from pathlib import Path

import pytest

from analysis.trend_analyzer import TrendAnalyzer, generate_report
from database.db_handler import FetchedURLStore, SlotDatabase
from scrapers.min_repo_scraper import (
    fetch_report_urls_from_html,
    parse_machine_stats_from_html,
    parse_report_page_from_html,
)


# =====================================================================
# リアルなHTMLフィクスチャ (複数日分)
# =====================================================================
TAG_PAGE_HTML = textwrap.dedent("""\
    <!DOCTYPE html>
    <html lang="ja">
    <head><title>レイト荒川沖 – みんレポ</title></head>
    <body>
    <main>
      <article>
        <h2 class="entry-title">
          <a href="https://min-repo.com/3001001/">2025/7/5(土) レイト荒川沖</a>
        </h2>
      </article>
      <article>
        <h2 class="entry-title">
          <a href="https://min-repo.com/3001002/">2025/6/25(水) レイト荒川沖</a>
        </h2>
      </article>
      <article>
        <h2 class="entry-title">
          <a href="https://min-repo.com/3001003/">2025/6/15(日) レイト荒川沖</a>
        </h2>
      </article>
      <article>
        <h2 class="entry-title">
          <a href="https://min-repo.com/3001004/">2025/6/5(木) レイト荒川沖</a>
        </h2>
      </article>
    </main>
    </body>
    </html>
""")


def _make_report_html(date_str: str, machines: list[dict]) -> str:
    """レポートページHTMLを動的生成する."""
    summary_rows = []
    detail_tables = []

    for m in machines:
        name = m["name"]
        units = m["units"]
        avg_diff = m["avg_diff"]
        avg_g = m["avg_g"]
        win_rate = m["win_rate"]
        payout_rate = m["payout_rate"]

        summary_rows.append(
            f'<tr><td>{name}</td><td>{len(units)}</td>'
            f'<td>{avg_diff:+,}</td><td>{avg_g:,}</td>'
            f'<td>{win_rate}%</td><td>{payout_rate}%</td></tr>'
        )

        unit_rows = "\n".join(
            f'<tr><td>{u["num"]}</td><td>{u["g"]:,}</td>'
            f'<td>{u["diff"]:+,}</td><td>{u["bb"]}</td><td>{u["rb"]}</td></tr>'
            for u in units
        )
        detail_tables.append(
            f'<h3>{name}</h3>\n<table>\n'
            f'<tr><th>台番号</th><th>G数</th><th>差枚</th><th>BB</th><th>RB</th></tr>\n'
            f'{unit_rows}\n</table>'
        )

    summary = (
        '<h2>機種別データ</h2>\n<table>\n'
        '<tr><th>機種</th><th>台数</th><th>平均差枚</th>'
        '<th>平均G数</th><th>勝率</th><th>出率</th></tr>\n'
        + "\n".join(summary_rows)
        + "\n</table>"
    )

    return (
        f'<!DOCTYPE html><html><head><title>{date_str} レイト荒川沖</title></head>'
        f'<body><main><article><div class="entry-content">'
        f'{summary}\n' + "\n".join(detail_tables) +
        f'</div></article></main></body></html>'
    )


# 各日のデータ
REPORT_DATA = {
    "2025-06-05": [
        {"name": "マイジャグラーV", "avg_diff": 1500, "avg_g": 7500,
         "win_rate": 80.0, "payout_rate": 112.0,
         "units": [
             {"num": 301, "g": 8500, "diff": 2100, "bb": 32, "rb": 18},
             {"num": 302, "g": 7200, "diff": 1800, "bb": 28, "rb": 15},
             {"num": 303, "g": 6800, "diff": 600, "bb": 22, "rb": 12},
         ]},
        {"name": "ハッピージャグラーVIII", "avg_diff": -200, "avg_g": 5000,
         "win_rate": 33.3, "payout_rate": 97.0,
         "units": [
             {"num": 401, "g": 5500, "diff": -400, "bb": 12, "rb": 8},
             {"num": 402, "g": 4800, "diff": 200, "bb": 14, "rb": 9},
             {"num": 403, "g": 4700, "diff": -400, "bb": 10, "rb": 7},
         ]},
        {"name": "アイムジャグラーEX", "avg_diff": 800, "avg_g": 6000,
         "win_rate": 66.7, "payout_rate": 106.0,
         "units": [
             {"num": 501, "g": 6500, "diff": 1200, "bb": 20, "rb": 14},
             {"num": 502, "g": 5800, "diff": 400, "bb": 16, "rb": 10},
             {"num": 503, "g": 5700, "diff": 800, "bb": 18, "rb": 12},
         ]},
    ],
    "2025-06-15": [
        {"name": "マイジャグラーV", "avg_diff": 1200, "avg_g": 7200,
         "win_rate": 75.0, "payout_rate": 109.0,
         "units": [
             {"num": 301, "g": 7800, "diff": 1800, "bb": 30, "rb": 17},
             {"num": 302, "g": 7000, "diff": 1000, "bb": 24, "rb": 14},
             {"num": 303, "g": 6500, "diff": 300, "bb": 20, "rb": 11},
             {"num": 304, "g": 7500, "diff": 1700, "bb": 28, "rb": 16},
         ]},
        {"name": "アイムジャグラーEX", "avg_diff": 1100, "avg_g": 7000,
         "win_rate": 80.0, "payout_rate": 108.0,
         "units": [
             {"num": 501, "g": 7500, "diff": 1500, "bb": 22, "rb": 15},
             {"num": 502, "g": 6800, "diff": 700, "bb": 18, "rb": 12},
         ]},
    ],
    "2025-06-25": [
        {"name": "マイジャグラーV", "avg_diff": 1000, "avg_g": 7000,
         "win_rate": 75.0, "payout_rate": 107.0,
         "units": [
             {"num": 301, "g": 7500, "diff": 1500, "bb": 26, "rb": 16},
             {"num": 302, "g": 6800, "diff": 500, "bb": 20, "rb": 13},
         ]},
        {"name": "ハッピージャグラーVIII", "avg_diff": 600, "avg_g": 6000,
         "win_rate": 50.0, "payout_rate": 104.0,
         "units": [
             {"num": 401, "g": 6500, "diff": 900, "bb": 18, "rb": 11},
             {"num": 402, "g": 5500, "diff": 300, "bb": 14, "rb": 9},
         ]},
    ],
    "2025-07-05": [
        {"name": "マイジャグラーV", "avg_diff": 1800, "avg_g": 7800,
         "win_rate": 80.0, "payout_rate": 112.0,
         "units": [
             {"num": 301, "g": 8200, "diff": 2500, "bb": 34, "rb": 20},
             {"num": 302, "g": 7600, "diff": 1600, "bb": 28, "rb": 17},
             {"num": 303, "g": 7600, "diff": 1300, "bb": 25, "rb": 15},
         ]},
        {"name": "ゴーゴージャグラー3", "avg_diff": 500, "avg_g": 5500,
         "win_rate": 50.0, "payout_rate": 103.0,
         "units": [
             {"num": 601, "g": 5800, "diff": 800, "bb": 16, "rb": 10},
             {"num": 602, "g": 5200, "diff": 200, "bb": 12, "rb": 8},
         ]},
    ],
}

REPORT_HTMLS = {
    dt: _make_report_html(dt, machines)
    for dt, machines in REPORT_DATA.items()
}


# =====================================================================
# テスト
# =====================================================================
class TestEndToEndSimulation:
    """レイト荒川沖の一気通貫シミュレーション."""

    def test_tag_page_parsing(self):
        """Step 1: タグページから4件のレポートURLを取得."""
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        assert len(links) == 4
        dates = [l.date for l in links]
        assert dates == sorted(dates, reverse=True)

    def test_report_parsing_all_dates(self):
        """Step 2: 各レポートページから台別 + 機種別データを抽出."""
        for date_str, html in REPORT_HTMLS.items():
            dt = datetime.fromisoformat(date_str)
            slot_records = parse_report_page_from_html(html, dt, "153")
            machine_stats = parse_machine_stats_from_html(html, dt, "153")

            expected_machines = REPORT_DATA[date_str]
            expected_units = sum(len(m["units"]) for m in expected_machines)

            assert len(slot_records) == expected_units, f"slot count mismatch for {date_str}"
            assert len(machine_stats) == len(expected_machines), f"stats count mismatch for {date_str}"

    def test_full_pipeline(self, tmp_path):
        """Step 1-5: タグページ → パース → DB保存 → 分析 → レポート出力."""
        # --- Step 1: タグページからURL取得 ---
        links = fetch_report_urls_from_html(TAG_PAGE_HTML)
        assert len(links) == 4

        # --- Step 2 & 3: パース → DB保存 ---
        db = SlotDatabase(tmp_path / "simulation.db")
        url_store = FetchedURLStore(tmp_path / "fetched.json")

        total_slots = 0
        total_stats = 0

        for link in links:
            date_str = link.date.strftime("%Y-%m-%d")
            html = REPORT_HTMLS.get(date_str)
            if html is None:
                continue

            slot_records = parse_report_page_from_html(html, link.date, "153")
            machine_stats = parse_machine_stats_from_html(html, link.date, "153")

            db.insert_slot_data(slot_records)
            db.insert_machine_stats(machine_stats)

            url_store.mark_fetched(link.url, "153", link.date)

            total_slots += len(slot_records)
            total_stats += len(machine_stats)

        # DB件数の検証
        assert db.count_slot_data(shop_id="153") == total_slots
        assert db.count_machine_stats(shop_id="153") == total_stats
        assert total_slots > 0
        assert total_stats > 0

        # URL Store の検証
        assert url_store.fetched_count() == 4
        for link in links:
            assert url_store.is_fetched(link.url)

        # --- Step 4: 分析 ---
        analyzer = TrendAnalyzer(db)
        result = analyzer.analyze("153")

        # 基本検証
        assert result.shop_id == "153"
        assert 5 in result.day_suffix_trends  # 4日分全て day_suffix=5

        # day_suffix=5 の分析結果
        trends_5 = result.day_suffix_trends[5]
        machine_names = {t.machine_name for t in trends_5}
        assert "マイジャグラーV" in machine_names

        # マイジャグラーV は4日分のデータがあるはず
        mj = [t for t in trends_5 if t.machine_name == "マイジャグラーV"][0]
        assert mj.count == 4

        # 全台系: 6/5(diff=1500,wr=80)→Yes, 6/15(diff=1200,wr=75)→Yes,
        #         6/25(diff=1000,wr=75)→Yes, 7/5(diff=1800,wr=80)→Yes
        assert mj.zentai_count == 4
        assert len(mj.zentai_dates) == 4

        # Tsumo-Rank
        assert 5 in result.tsumo_ranks
        ranks = result.tsumo_ranks[5]
        assert ranks[0].machine_name == "マイジャグラーV"  # 最高スコア

        # --- Step 5: レポート出力 ---
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        md = generate_report(
            result,
            shop_name="麗都荒川沖",
            day_suffix_targets=[5, 0],
            report_date=date(2025, 7, 10),
        )

        out_path = output_dir / "report_153_20250710.md"
        out_path.write_text(md, encoding="utf-8")

        # レポート内容の検証
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "# 麗都荒川沖 傾向分析レポート" in content
        assert "店舗ID: 153" in content
        assert "5の日 おすすめ機種 TOP5" in content
        assert "マイジャグラーV" in content
        assert "全台系の実績日" in content  # 全台系日付リスト

        # 具体的な日付がレポートに含まれること
        assert "2025-06-05" in content
        assert "2025-07-05" in content

        db.close()

    def test_data_integrity(self, tmp_path):
        """DB に保存されたデータの整合性を詳細に検証."""
        db = SlotDatabase(tmp_path / "integrity.db")

        # 全日分をDB投入
        for date_str, html in REPORT_HTMLS.items():
            dt = datetime.fromisoformat(date_str)
            db.insert_slot_data(parse_report_page_from_html(html, dt, "153"))
            db.insert_machine_stats(parse_machine_stats_from_html(html, dt, "153"))

        # 各日のデータを個別検証
        for date_str, machines in REPORT_DATA.items():
            stat_rows = db.fetch_machine_stats(shop_id="153", date=date_str)
            assert len(stat_rows) == len(machines), f"stats mismatch: {date_str}"

            for m in machines:
                matched = [r for r in stat_rows if r["machine_name"] == m["name"]]
                assert len(matched) == 1, f'{m["name"]} not found in DB for {date_str}'
                r = matched[0]
                assert r["avg_diff_payout"] == m["avg_diff"]
                assert r["unit_count"] == len(m["units"])
                assert abs(r["win_rate"] - m["win_rate"]) < 0.1

            slot_rows = db.fetch_slot_data(shop_id="153", date=date_str)
            expected_units = sum(len(m["units"]) for m in machines)
            assert len(slot_rows) == expected_units, f"slots mismatch: {date_str}"

        db.close()

    def test_duplicate_insert_safe(self, tmp_path):
        """同じデータを2回投入しても重複しないこと."""
        db = SlotDatabase(tmp_path / "dup.db")

        html = REPORT_HTMLS["2025-06-05"]
        dt = datetime(2025, 6, 5)

        db.insert_slot_data(parse_report_page_from_html(html, dt, "153"))
        db.insert_machine_stats(parse_machine_stats_from_html(html, dt, "153"))

        count1_slot = db.count_slot_data()
        count1_stat = db.count_machine_stats()

        # 2回目: 重複は IGNORE
        db.insert_slot_data(parse_report_page_from_html(html, dt, "153"))
        db.insert_machine_stats(parse_machine_stats_from_html(html, dt, "153"))

        assert db.count_slot_data() == count1_slot
        assert db.count_machine_stats() == count1_stat

        db.close()
