"""傾向分析エンジン (TrendAnalyzer) + Tsumo-Rank スコアリング.

SlotDatabase に蓄積された machine_stats データを読み出し、
特定日・曜日・祝日・新装開店ごとの機種別傾向を分析する。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Sequence

from database.db_handler import SlotDatabase
from utils.date_helper import get_date_attributes

logger = logging.getLogger(__name__)

# 曜日名 (表示用)
_DOW_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


# ---------------------------------------------------------------------------
# 分析結果の型
# ---------------------------------------------------------------------------
@dataclass
class MachineTrend:
    """1機種の傾向集計結果."""

    machine_name: str
    count: int = 0  # データ日数
    avg_diff_payout: float = 0.0  # 平均差枚 (全日平均)
    avg_win_rate: float = 0.0  # 平均勝率 (%)
    avg_payout_rate: float = 0.0  # 平均出率 (%)
    avg_g_count: float = 0.0  # 平均G数
    zentai_count: int = 0  # 全台系発生回数


@dataclass
class TsumoRank:
    """Tsumo-Rank スコアリング結果."""

    machine_name: str
    score: float = 0.0
    avg_diff_payout: float = 0.0
    avg_win_rate: float = 0.0
    zentai_count: int = 0
    data_count: int = 0


@dataclass
class AnalysisResult:
    """TrendAnalyzer の全分析結果をまとめるコンテナ."""

    shop_id: str
    # 特定日分析: {day_suffix: [MachineTrend, ...]}
    day_suffix_trends: dict[int, list[MachineTrend]] = field(default_factory=dict)
    # ゾロ目日分析: [MachineTrend, ...]
    zoro_trends: list[MachineTrend] = field(default_factory=list)
    # 新装開店(前日データなし)分析: [MachineTrend, ...]
    post_holiday_trends: list[MachineTrend] = field(default_factory=list)
    # 曜日分析: {day_of_week(0-6): [MachineTrend, ...]}
    weekday_trends: dict[int, list[MachineTrend]] = field(default_factory=dict)
    # 祝日分析: [MachineTrend, ...]
    holiday_trends: list[MachineTrend] = field(default_factory=list)
    # Tsumo-Rank: {day_suffix: [TsumoRank, ...]}
    tsumo_ranks: dict[int, list[TsumoRank]] = field(default_factory=dict)
    # ゾロ目 Tsumo-Rank: [TsumoRank, ...]
    zoro_tsumo_ranks: list[TsumoRank] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 全台系判定の閾値
# ---------------------------------------------------------------------------
ZENTAI_WIN_RATE_THRESHOLD = 75.0  # 勝率 75% 以上
ZENTAI_AVG_DIFF_THRESHOLD = 1000  # 平均差枚 +1000 以上


# ---------------------------------------------------------------------------
# TrendAnalyzer
# ---------------------------------------------------------------------------
class TrendAnalyzer:
    """SlotDatabase の machine_stats データを読み出して傾向分析を行う."""

    def __init__(self, db: SlotDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # 内部: DB からデータ取得
    # ------------------------------------------------------------------
    def _load_stats(self, shop_id: str) -> list[dict[str, Any]]:
        """指定店舗の全 machine_stats を読み込む."""
        return self._db.fetch_machine_stats(shop_id=shop_id)

    def _all_dates_for_shop(self, shop_id: str) -> set[date]:
        """指定店舗のデータが存在する全日付を set で返す."""
        rows = self._db.fetch_machine_stats(shop_id=shop_id)
        dates: set[date] = set()
        for r in rows:
            dates.add(date.fromisoformat(r["date"]))
        return dates

    def list_shop_ids(self) -> list[str]:
        """DB 内の全 shop_id を一意に取得する."""
        rows = self._db._conn.execute(
            "SELECT DISTINCT shop_id FROM machine_stats ORDER BY shop_id"
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # 日付属性でグルーピング
    # ------------------------------------------------------------------
    def _annotate_stats(
        self, stats: list[dict[str, Any]], past_dates: set[date]
    ) -> list[dict[str, Any]]:
        """machine_stats の各行に日付属性を付加する."""
        for row in stats:
            d = date.fromisoformat(row["date"])
            attrs = get_date_attributes(d, past_dates)
            row.update(attrs)
        return stats

    # ------------------------------------------------------------------
    # 集計ヘルパー
    # ------------------------------------------------------------------
    @staticmethod
    def _aggregate(rows: list[dict[str, Any]]) -> list[MachineTrend]:
        """machine_stats 行のリストを機種別に集計する."""
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            buckets[r["machine_name"]].append(r)

        trends: list[MachineTrend] = []
        for name, items in buckets.items():
            n = len(items)
            avg_diff = sum(r["avg_diff_payout"] for r in items) / n
            avg_wr = sum(r["win_rate"] for r in items) / n
            avg_pr = sum(r["payout_rate"] for r in items) / n
            avg_gc = sum(r["avg_g_count"] for r in items) / n
            zentai = sum(
                1
                for r in items
                if r["win_rate"] >= ZENTAI_WIN_RATE_THRESHOLD
                and r["avg_diff_payout"] >= ZENTAI_AVG_DIFF_THRESHOLD
            )
            trends.append(
                MachineTrend(
                    machine_name=name,
                    count=n,
                    avg_diff_payout=round(avg_diff, 1),
                    avg_win_rate=round(avg_wr, 1),
                    avg_payout_rate=round(avg_pr, 1),
                    avg_g_count=round(avg_gc, 1),
                    zentai_count=zentai,
                )
            )
        # 平均差枚降順でソート
        trends.sort(key=lambda t: t.avg_diff_payout, reverse=True)
        return trends

    # ------------------------------------------------------------------
    # Tsumo-Rank スコア計算
    # ------------------------------------------------------------------
    @staticmethod
    def compute_tsumo_rank(trends: list[MachineTrend]) -> list[TsumoRank]:
        """MachineTrend リストから Tsumo-Rank スコアを算出する.

        スコア = (平均差枚 * 0.4) + (勝率 * 10) + (全台系回数 * 100)
        """
        ranks: list[TsumoRank] = []
        for t in trends:
            score = (t.avg_diff_payout * 0.4) + (t.avg_win_rate * 10) + (t.zentai_count * 100)
            ranks.append(
                TsumoRank(
                    machine_name=t.machine_name,
                    score=round(score, 1),
                    avg_diff_payout=t.avg_diff_payout,
                    avg_win_rate=t.avg_win_rate,
                    zentai_count=t.zentai_count,
                    data_count=t.count,
                )
            )
        ranks.sort(key=lambda r: r.score, reverse=True)
        return ranks

    # ------------------------------------------------------------------
    # 公開 API: 全分析実行
    # ------------------------------------------------------------------
    def analyze(self, shop_id: str) -> AnalysisResult:
        """指定店舗の全傾向分析を実行して AnalysisResult を返す."""
        stats = self._load_stats(shop_id)
        if not stats:
            logger.warning("No data for shop_id=%s", shop_id)
            return AnalysisResult(shop_id=shop_id)

        past_dates = self._all_dates_for_shop(shop_id)
        annotated = self._annotate_stats(stats, past_dates)

        result = AnalysisResult(shop_id=shop_id)

        # --- 特定日分析 (day_suffix 0-9) ---
        suffix_buckets: dict[int, list[dict]] = defaultdict(list)
        for r in annotated:
            suffix_buckets[r["day_suffix"]].append(r)

        for suffix in range(10):
            rows = suffix_buckets.get(suffix, [])
            if rows:
                trends = self._aggregate(rows)
                result.day_suffix_trends[suffix] = trends
                result.tsumo_ranks[suffix] = self.compute_tsumo_rank(trends)

        # --- ゾロ目日分析 ---
        zoro_rows = [r for r in annotated if r["is_zoro"]]
        if zoro_rows:
            result.zoro_trends = self._aggregate(zoro_rows)
            result.zoro_tsumo_ranks = self.compute_tsumo_rank(result.zoro_trends)

        # --- 新装開店 (前日データなし) ---
        post_holiday_rows = [r for r in annotated if r["is_post_holiday"]]
        if post_holiday_rows:
            result.post_holiday_trends = self._aggregate(post_holiday_rows)

        # --- 曜日分析 ---
        dow_buckets: dict[int, list[dict]] = defaultdict(list)
        for r in annotated:
            dow_buckets[r["day_of_week"]].append(r)
        for dow in range(7):
            rows = dow_buckets.get(dow, [])
            if rows:
                result.weekday_trends[dow] = self._aggregate(rows)

        # --- 祝日分析 ---
        holiday_rows = [r for r in annotated if r["is_holiday"]]
        if holiday_rows:
            result.holiday_trends = self._aggregate(holiday_rows)

        logger.info(
            "Analysis complete for shop_id=%s: %d dates, %d stats rows",
            shop_id,
            len(past_dates),
            len(stats),
        )
        return result

    def analyze_all_shops(self) -> dict[str, AnalysisResult]:
        """DB 内の全店舗について分析を実行する."""
        results: dict[str, AnalysisResult] = {}
        for shop_id in self.list_shop_ids():
            results[shop_id] = self.analyze(shop_id)
        return results


# ---------------------------------------------------------------------------
# Markdown レポート生成
# ---------------------------------------------------------------------------
def _fmt_rank_table(ranks: list[TsumoRank], top_n: int = 5) -> str:
    """TsumoRank リストを Markdown テーブルに変換する."""
    lines = [
        "| 順位 | 機種 | スコア | 平均差枚 | 勝率 | 全台系 | データ数 |",
        "|---:|:---|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(ranks[:top_n], 1):
        lines.append(
            f"| {i} | {r.machine_name} | {r.score:.1f} "
            f"| {r.avg_diff_payout:+.0f} | {r.avg_win_rate:.1f}% "
            f"| {r.zentai_count} | {r.data_count} |"
        )
    return "\n".join(lines)


def _fmt_trend_table(trends: list[MachineTrend], top_n: int = 10) -> str:
    """MachineTrend リストを Markdown テーブルに変換する."""
    lines = [
        "| 機種 | 平均差枚 | 勝率 | 出率 | 平均G数 | 全台系 | 日数 |",
        "|:---|---:|---:|---:|---:|---:|---:|",
    ]
    for t in trends[:top_n]:
        lines.append(
            f"| {t.machine_name} | {t.avg_diff_payout:+.0f} "
            f"| {t.avg_win_rate:.1f}% | {t.avg_payout_rate:.1f}% "
            f"| {t.avg_g_count:.0f} | {t.zentai_count} | {t.count} |"
        )
    return "\n".join(lines)


def generate_report(
    result: AnalysisResult,
    shop_name: str = "",
    day_suffix_targets: Sequence[int] | None = None,
    report_date: date | None = None,
) -> str:
    """AnalysisResult から Markdown レポートを生成する.

    Args:
        result: TrendAnalyzer.analyze() の戻り値
        shop_name: 店舗名 (表示用)
        day_suffix_targets: レポートに含める特定日 (1の位) リスト
        report_date: レポート出力日 (省略時は今日)

    Returns:
        Markdown 形式のレポート文字列
    """
    if report_date is None:
        report_date = date.today()

    title = shop_name or f"Shop {result.shop_id}"
    lines: list[str] = []
    lines.append(f"# {title} 傾向分析レポート")
    lines.append(f"")
    lines.append(f"> 生成日: {report_date}  |  店舗ID: {result.shop_id}")
    lines.append("")

    # --- 特定日のおすすめ機種 TOP5 ---
    targets = day_suffix_targets or sorted(result.tsumo_ranks.keys())
    for suffix in targets:
        ranks = result.tsumo_ranks.get(suffix, [])
        if not ranks:
            continue
        lines.append(f"## {suffix}の日 おすすめ機種 TOP5")
        lines.append("")
        lines.append(_fmt_rank_table(ranks, top_n=5))
        lines.append("")

    # --- ゾロ目日 ---
    if result.zoro_tsumo_ranks:
        lines.append("## ゾロ目の日 おすすめ機種 TOP5")
        lines.append("")
        lines.append(_fmt_rank_table(result.zoro_tsumo_ranks, top_n=5))
        lines.append("")

    # --- 新装開店で強かった機種 ---
    if result.post_holiday_trends:
        lines.append("## 新装開店 (前日データなし) 機種ランキング")
        lines.append("")
        lines.append(_fmt_trend_table(result.post_holiday_trends, top_n=10))
        lines.append("")

    # --- 曜日別傾向 ---
    if result.weekday_trends:
        lines.append("## 曜日別傾向 (TOP3)")
        lines.append("")
        for dow in range(7):
            trends = result.weekday_trends.get(dow, [])
            if not trends:
                continue
            total_diff = sum(t.avg_diff_payout * t.count for t in trends)
            total_days = sum(t.count for t in trends)
            avg_g = (
                sum(t.avg_g_count * t.count for t in trends) / total_days
                if total_days
                else 0
            )
            lines.append(f"### {_DOW_NAMES[dow]}曜日 ({total_days}日分)")
            lines.append(f"")
            lines.append(f"- 総差枚合計 (加重): {total_diff:+,.0f}")
            lines.append(f"- 加重平均G数: {avg_g:,.0f}")
            lines.append(f"")
            top3 = sorted(trends, key=lambda t: t.avg_diff_payout, reverse=True)[:3]
            for i, t in enumerate(top3, 1):
                lines.append(
                    f"{i}. **{t.machine_name}** — "
                    f"平均差枚 {t.avg_diff_payout:+.0f} / "
                    f"勝率 {t.avg_win_rate:.1f}%"
                )
            lines.append("")

    # --- 祝日傾向 ---
    if result.holiday_trends:
        lines.append("## 祝日 機種ランキング")
        lines.append("")
        lines.append(_fmt_trend_table(result.holiday_trends, top_n=10))
        lines.append("")

    return "\n".join(lines)
