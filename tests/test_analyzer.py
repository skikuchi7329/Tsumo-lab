"""analysis/trend_analyzer.py のテスト.

ダミーデータを SQLite に投入し、特定日ごとの機種ランキングが
正しく出力されるかを検証する。
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from analysis.trend_analyzer import (
    ZENTAI_AVG_DIFF_THRESHOLD,
    ZENTAI_WIN_RATE_THRESHOLD,
    AnalysisResult,
    MachineTrend,
    TrendAnalyzer,
    TsumoRank,
    generate_report,
)
from database.db_handler import SlotDatabase
from models.schema import MachineStats


# =====================================================================
# ダミーデータ生成
# =====================================================================
def _make_stat(
    dt: date,
    shop_id: str,
    machine_name: str,
    unit_count: int = 5,
    avg_diff: int = 0,
    avg_g: int = 5000,
    win_rate: float = 50.0,
    payout_rate: float = 100.0,
) -> MachineStats:
    return MachineStats(
        date=datetime(dt.year, dt.month, dt.day),
        shop_id=shop_id,
        machine_name=machine_name,
        unit_count=unit_count,
        avg_diff_payout=avg_diff,
        avg_g_count=avg_g,
        win_rate=win_rate,
        payout_rate=payout_rate,
    )


def _seed_shop_153(db: SlotDatabase) -> None:
    """shop_id=153 用ダミーデータ.

    日付設計:
      2025-06-05 (木) day_suffix=5
      2025-06-07 (土) day_suffix=7, ゾロ目=False
      2025-06-11 (水) day_suffix=1, ゾロ目=True (11日)
      2025-06-15 (日) day_suffix=5
      2025-06-17 (火) day_suffix=7
      2025-06-22 (日) day_suffix=2, ゾロ目=True (22日)
      2025-06-25 (水) day_suffix=5
      2025-07-05 (土) day_suffix=5
      2025-07-07 (月) day_suffix=7, ゾロ目=True (7/7)

    全台系条件: 勝率≥75%, 平均差枚≥+1000
    """
    records = [
        # --- 6/5 (day_suffix=5) ---
        _make_stat(date(2025, 6, 5), "153", "マイジャグラーV",
                   avg_diff=1500, avg_g=7500, win_rate=80.0, payout_rate=112.0),
        _make_stat(date(2025, 6, 5), "153", "ハッピージャグラーVIII",
                   avg_diff=-200, avg_g=5000, win_rate=30.0, payout_rate=97.0),
        _make_stat(date(2025, 6, 5), "153", "アイムジャグラーEX",
                   avg_diff=800, avg_g=6000, win_rate=60.0, payout_rate=106.0),
        # --- 6/7 (day_suffix=7) ---
        _make_stat(date(2025, 6, 7), "153", "マイジャグラーV",
                   avg_diff=2000, avg_g=8000, win_rate=90.0, payout_rate=115.0),
        _make_stat(date(2025, 6, 7), "153", "ゴーゴージャグラー3",
                   avg_diff=1200, avg_g=7000, win_rate=75.0, payout_rate=110.0),
        _make_stat(date(2025, 6, 7), "153", "アイムジャグラーEX",
                   avg_diff=-500, avg_g=4000, win_rate=20.0, payout_rate=95.0),
        # --- 6/11 (day_suffix=1, ゾロ目) ---
        _make_stat(date(2025, 6, 11), "153", "マイジャグラーV",
                   avg_diff=3000, avg_g=9000, win_rate=100.0, payout_rate=120.0),
        _make_stat(date(2025, 6, 11), "153", "ハッピージャグラーVIII",
                   avg_diff=1500, avg_g=6500, win_rate=80.0, payout_rate=112.0),
        # --- 6/15 (day_suffix=5, 日曜) ---
        _make_stat(date(2025, 6, 15), "153", "マイジャグラーV",
                   avg_diff=500, avg_g=6000, win_rate=60.0, payout_rate=104.0),
        _make_stat(date(2025, 6, 15), "153", "アイムジャグラーEX",
                   avg_diff=1100, avg_g=7000, win_rate=80.0, payout_rate=108.0),
        # --- 6/17 (day_suffix=7) ---
        _make_stat(date(2025, 6, 17), "153", "マイジャグラーV",
                   avg_diff=1800, avg_g=7500, win_rate=85.0, payout_rate=113.0),
        _make_stat(date(2025, 6, 17), "153", "ゴーゴージャグラー3",
                   avg_diff=500, avg_g=5500, win_rate=50.0, payout_rate=103.0),
        # --- 6/22 (day_suffix=2, ゾロ目, 日曜) ---
        _make_stat(date(2025, 6, 22), "153", "マイジャグラーV",
                   avg_diff=2500, avg_g=8500, win_rate=90.0, payout_rate=118.0),
        _make_stat(date(2025, 6, 22), "153", "ハッピージャグラーVIII",
                   avg_diff=-100, avg_g=5000, win_rate=40.0, payout_rate=99.0),
        # --- 6/25 (day_suffix=5) ---
        _make_stat(date(2025, 6, 25), "153", "マイジャグラーV",
                   avg_diff=1000, avg_g=7000, win_rate=75.0, payout_rate=107.0),
        _make_stat(date(2025, 6, 25), "153", "アイムジャグラーEX",
                   avg_diff=200, avg_g=5500, win_rate=50.0, payout_rate=102.0),
        # --- 7/5 (day_suffix=5) ---
        _make_stat(date(2025, 7, 5), "153", "マイジャグラーV",
                   avg_diff=1200, avg_g=7200, win_rate=80.0, payout_rate=109.0),
        _make_stat(date(2025, 7, 5), "153", "ハッピージャグラーVIII",
                   avg_diff=600, avg_g=6000, win_rate=55.0, payout_rate=104.0),
        # --- 7/7 (day_suffix=7, ゾロ目 7/7) ---
        _make_stat(date(2025, 7, 7), "153", "マイジャグラーV",
                   avg_diff=2200, avg_g=8200, win_rate=95.0, payout_rate=116.0),
        _make_stat(date(2025, 7, 7), "153", "ゴーゴージャグラー3",
                   avg_diff=1800, avg_g=7500, win_rate=85.0, payout_rate=112.0),
        _make_stat(date(2025, 7, 7), "153", "アイムジャグラーEX",
                   avg_diff=300, avg_g=5000, win_rate=40.0, payout_rate=102.0),
    ]
    db.insert_machine_stats(records)


def _seed_shop_200(db: SlotDatabase) -> None:
    """shop_id=200 用ダミーデータ (別店舗)."""
    records = [
        _make_stat(date(2025, 6, 5), "200", "押忍！番長ZERO",
                   avg_diff=2000, avg_g=8000, win_rate=85.0, payout_rate=114.0),
        _make_stat(date(2025, 6, 5), "200", "バジリスク絆2",
                   avg_diff=-300, avg_g=4000, win_rate=25.0, payout_rate=96.0),
        _make_stat(date(2025, 6, 15), "200", "押忍！番長ZERO",
                   avg_diff=1500, avg_g=7000, win_rate=80.0, payout_rate=111.0),
    ]
    db.insert_machine_stats(records)


# =====================================================================
# TrendAnalyzer 基本テスト
# =====================================================================
class TestTrendAnalyzer:
    def test_analyze_returns_result(self, tmp_path):
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        analyzer = TrendAnalyzer(db)
        result = analyzer.analyze("153")

        assert isinstance(result, AnalysisResult)
        assert result.shop_id == "153"
        db.close()

    def test_day_suffix_trends_populated(self, tmp_path):
        """特定日ごとに集計データが入ること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")

        # day_suffix=5 のデータは 6/5, 6/15, 6/25, 7/5 の 4 日分
        assert 5 in result.day_suffix_trends
        trends_5 = result.day_suffix_trends[5]
        assert len(trends_5) > 0  # 少なくとも1機種以上

        # day_suffix=7 のデータは 6/7, 6/17, 7/7 の 3 日分
        assert 7 in result.day_suffix_trends
        db.close()

    def test_day_suffix_5_myjag_is_top(self, tmp_path):
        """5の日でマイジャグラーVが最上位であること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        trends_5 = result.day_suffix_trends[5]
        # 平均差枚降順ソートなので先頭が最高
        assert trends_5[0].machine_name == "マイジャグラーV"
        db.close()

    def test_day_suffix_7_ranking(self, tmp_path):
        """7の日のランキング: マイジャグラーV > ゴーゴージャグラー3."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        trends_7 = result.day_suffix_trends[7]
        names = [t.machine_name for t in trends_7]
        assert names.index("マイジャグラーV") < names.index("ゴーゴージャグラー3")
        db.close()

    def test_zoro_trends(self, tmp_path):
        """ゾロ目日 (6/11, 6/22, 7/7) の集計."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        assert len(result.zoro_trends) > 0
        # マイジャグラーV はゾロ目日に 3/3 日データあり
        mj = [t for t in result.zoro_trends if t.machine_name == "マイジャグラーV"]
        assert len(mj) == 1
        assert mj[0].count == 3
        db.close()

    def test_post_holiday_trends(self, tmp_path):
        """前日データなしの日の集計 (新装開店分析)."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        # 前日データがない日: データ日付は 6/5,6/7,6/11,6/15,6/17,6/22,6/25,7/5,7/7
        # 連続ではないので大半の日が is_post_holiday=True
        assert len(result.post_holiday_trends) > 0
        db.close()

    def test_weekday_trends(self, tmp_path):
        """曜日別の集計."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        assert len(result.weekday_trends) > 0
        # 日曜日 (6=日) のデータ: 6/15(日), 6/22(日)
        if 6 in result.weekday_trends:
            sun_trends = result.weekday_trends[6]
            assert len(sun_trends) > 0
        db.close()

    def test_empty_shop(self, tmp_path):
        """データがない店舗は空結果."""
        db = SlotDatabase(tmp_path / "test.db")
        result = TrendAnalyzer(db).analyze("999")
        assert result.shop_id == "999"
        assert len(result.day_suffix_trends) == 0
        db.close()


# =====================================================================
# 全台系判定
# =====================================================================
class TestZentaiDetection:
    def test_zentai_counted(self, tmp_path):
        """全台系条件 (勝率≥75%, 平均差枚≥+1000) を満たす日がカウントされること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")

        # day_suffix=7 でのマイジャグラーV:
        #   6/7:  avg_diff=2000, win_rate=90  → 全台系
        #   6/17: avg_diff=1800, win_rate=85  → 全台系
        #   7/7:  avg_diff=2200, win_rate=95  → 全台系
        trends_7 = result.day_suffix_trends[7]
        mj = [t for t in trends_7 if t.machine_name == "マイジャグラーV"][0]
        assert mj.zentai_count == 3  # 3日とも全台系

    def test_zentai_not_counted_below_threshold(self, tmp_path):
        """閾値以下は全台系にカウントされないこと."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")

        # day_suffix=7 でのアイムジャグラーEX:
        #   6/7:  avg_diff=-500, win_rate=20  → 非全台系
        #   7/7:  avg_diff=300, win_rate=40   → 非全台系
        trends_7 = result.day_suffix_trends[7]
        aim = [t for t in trends_7 if t.machine_name == "アイムジャグラーEX"][0]
        assert aim.zentai_count == 0


# =====================================================================
# Tsumo-Rank スコアリング
# =====================================================================
class TestTsumoRank:
    def test_tsumo_ranks_populated(self, tmp_path):
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        assert 7 in result.tsumo_ranks
        assert len(result.tsumo_ranks[7]) > 0
        db.close()

    def test_tsumo_rank_score_formula(self, tmp_path):
        """スコア = (平均差枚 * 0.4) + (勝率 * 10) + (全台系回数 * 100)."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        ranks_7 = result.tsumo_ranks[7]

        # マイジャグラーV (day_suffix=7):
        #   avg_diff = (2000+1800+2200)/3 = 2000
        #   avg_win_rate = (90+85+95)/3 = 90
        #   zentai_count = 3
        #   score = 2000*0.4 + 90*10 + 3*100 = 800+900+300 = 2000
        mj = [r for r in ranks_7 if r.machine_name == "マイジャグラーV"][0]
        assert abs(mj.avg_diff_payout - 2000.0) < 1.0
        assert abs(mj.avg_win_rate - 90.0) < 1.0
        assert mj.zentai_count == 3
        expected_score = 2000 * 0.4 + 90 * 10 + 3 * 100
        assert abs(mj.score - expected_score) < 1.0

    def test_tsumo_rank_sorted_desc(self, tmp_path):
        """スコア降順にソートされること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        for suffix, ranks in result.tsumo_ranks.items():
            scores = [r.score for r in ranks]
            assert scores == sorted(scores, reverse=True), f"suffix={suffix} not sorted"
        db.close()

    def test_tsumo_rank_top1_is_myjag_on_7(self, tmp_path):
        """7の日で Tsumo-Rank 1位がマイジャグラーVであること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        assert result.tsumo_ranks[7][0].machine_name == "マイジャグラーV"
        db.close()

    def test_zoro_tsumo_ranks(self, tmp_path):
        """ゾロ目日の Tsumo-Rank."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        assert len(result.zoro_tsumo_ranks) > 0
        assert result.zoro_tsumo_ranks[0].machine_name == "マイジャグラーV"
        db.close()


# =====================================================================
# 全店舗分析
# =====================================================================
class TestMultiShop:
    def test_analyze_all_shops(self, tmp_path):
        """DB 内の全店舗を自動検出して分析できること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)
        _seed_shop_200(db)

        analyzer = TrendAnalyzer(db)
        results = analyzer.analyze_all_shops()

        assert "153" in results
        assert "200" in results
        assert results["153"].shop_id == "153"
        assert results["200"].shop_id == "200"
        db.close()

    def test_list_shop_ids(self, tmp_path):
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)
        _seed_shop_200(db)

        analyzer = TrendAnalyzer(db)
        ids = analyzer.list_shop_ids()
        assert "153" in ids
        assert "200" in ids
        db.close()

    def test_shop_200_results(self, tmp_path):
        """店舗200のデータが店舗153に混入しないこと."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)
        _seed_shop_200(db)

        analyzer = TrendAnalyzer(db)
        r153 = analyzer.analyze("153")
        r200 = analyzer.analyze("200")

        # 店舗200には「押忍！番長ZERO」があるが、店舗153にはない
        all_names_153 = set()
        for trends in r153.day_suffix_trends.values():
            for t in trends:
                all_names_153.add(t.machine_name)
        assert "押忍！番長ZERO" not in all_names_153

        all_names_200 = set()
        for trends in r200.day_suffix_trends.values():
            for t in trends:
                all_names_200.add(t.machine_name)
        assert "押忍！番長ZERO" in all_names_200
        assert "マイジャグラーV" not in all_names_200
        db.close()


# =====================================================================
# Markdown レポート生成
# =====================================================================
class TestGenerateReport:
    def test_report_contains_sections(self, tmp_path):
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        md = generate_report(
            result,
            shop_name="麗都荒川沖",
            day_suffix_targets=[5, 7],
            report_date=date(2025, 7, 10),
        )

        assert "# 麗都荒川沖 傾向分析レポート" in md
        assert "店舗ID: 153" in md
        assert "5の日 おすすめ機種 TOP5" in md
        assert "7の日 おすすめ機種 TOP5" in md
        assert "ゾロ目の日 おすすめ機種 TOP5" in md
        assert "新装開店" in md
        assert "曜日別傾向" in md
        assert "マイジャグラーV" in md
        db.close()

    def test_report_ranking_tables(self, tmp_path):
        """テーブルに順位・スコア・差枚が含まれること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        md = generate_report(result, day_suffix_targets=[7])

        # Markdown テーブルヘッダ
        assert "| 順位 |" in md
        assert "| スコア |" in md or "スコア" in md
        assert "| 1 |" in md  # 少なくとも1位のレコード
        db.close()

    def test_report_only_specified_suffixes(self, tmp_path):
        """day_suffix_targets で指定した特定日のみ出力されること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")
        md = generate_report(result, day_suffix_targets=[7])

        assert "7の日 おすすめ機種 TOP5" in md
        assert "5の日 おすすめ機種 TOP5" not in md
        db.close()

    def test_empty_result_no_crash(self, tmp_path):
        """空の分析結果でもクラッシュしないこと."""
        result = AnalysisResult(shop_id="999")
        md = generate_report(result, shop_name="テスト店")
        assert "# テスト店 傾向分析レポート" in md

    def test_report_for_shop_200(self, tmp_path):
        """別店舗のレポートが正しく出力されること."""
        db = SlotDatabase(tmp_path / "test.db")
        _seed_shop_200(db)

        result = TrendAnalyzer(db).analyze("200")
        md = generate_report(result, shop_name="テスト店B")

        assert "テスト店B" in md
        assert "押忍！番長ZERO" in md
        db.close()


# =====================================================================
# 統合テスト: ダミーデータ → 分析 → レポート
# =====================================================================
class TestEndToEnd:
    def test_full_flow(self, tmp_path):
        """ダミーデータ投入 → 分析 → Markdown 出力 → ファイル保存."""
        db = SlotDatabase(tmp_path / "e2e.db")
        _seed_shop_153(db)
        _seed_shop_200(db)

        analyzer = TrendAnalyzer(db)

        # 全店舗分析
        all_results = analyzer.analyze_all_shops()
        assert len(all_results) == 2

        # 各店舗のレポート生成・ファイル保存
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        for sid, result in all_results.items():
            md = generate_report(result, report_date=date(2025, 7, 10))
            out_path = output_dir / f"report_{sid}.md"
            out_path.write_text(md, encoding="utf-8")
            assert out_path.exists()
            content = out_path.read_text(encoding="utf-8")
            assert len(content) > 100  # 空でないこと

        db.close()

    def test_ranking_values_accurate(self, tmp_path):
        """具体的な数値が正確であることの詳細検証."""
        db = SlotDatabase(tmp_path / "detail.db")
        _seed_shop_153(db)

        result = TrendAnalyzer(db).analyze("153")

        # --- day_suffix=5 のマイジャグラーV ---
        # 6/5: diff=1500, wr=80, pr=112
        # 6/15: diff=500, wr=60, pr=104
        # 6/25: diff=1000, wr=75, pr=107
        # 7/5: diff=1200, wr=80, pr=109
        # → avg_diff = (1500+500+1000+1200)/4 = 1050
        # → avg_wr = (80+60+75+80)/4 = 73.75
        # → avg_pr = (112+104+107+109)/4 = 108.0
        # → 全台系: 6/5 (wr=80,diff=1500)→Yes, 6/25 (wr=75,diff=1000)→Yes, 7/5(wr=80,diff=1200)→Yes
        #            6/15 (wr=60)→No → zentai_count=3
        trends_5 = result.day_suffix_trends[5]
        mj = [t for t in trends_5 if t.machine_name == "マイジャグラーV"][0]
        assert mj.count == 4
        assert abs(mj.avg_diff_payout - 1050.0) < 1.0
        assert abs(mj.avg_win_rate - 73.75) < 0.1
        assert abs(mj.avg_payout_rate - 108.0) < 0.1
        assert mj.zentai_count == 3

        # Tsumo-Rank for suffix=5 マイジャグラーV
        ranks_5 = result.tsumo_ranks[5]
        mj_rank = [r for r in ranks_5 if r.machine_name == "マイジャグラーV"][0]
        expected = 1050 * 0.4 + 73.75 * 10 + 3 * 100
        # = 420 + 737.5 + 300 = 1457.5
        assert abs(mj_rank.score - expected) < 1.0

        db.close()
