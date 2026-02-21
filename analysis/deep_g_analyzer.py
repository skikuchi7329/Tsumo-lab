"""Deep-G-Analysis: 個別台データに基づく高設定推測 & ローテーション分析エンジン.

slot_data (台別データ) を読み込み、以下の分析を行う:
  1. 高設定濃厚タグ: AT機で7000G以上稼働 かつ 差枚が大きく凹んでいない
  2. ノーマル優秀タグ: 合算確率が設定6相当以上
  3. ピン投入傾向: 単品(ピン)での高設定投入パターンを機種別に集計
  4. 末尾分析: 台番号の下一桁ごとのパフォーマンス
  5. ローテーション分析: 全台系/半分系のローテーション検出 & 次回予測
  6. The Oracle: 全分析を統合した狙い目アドバイス生成
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from database.db_handler import SlotDatabase
from utils.machine_alias import MachineAliasResolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 閾値定数
# ---------------------------------------------------------------------------
AT_G_COUNT_THRESHOLD = 7000       # AT機の高稼働判定 (7000G以上)
HIGH_SETTING_DIFF_FLOOR = -1000   # 「大きく凹んでいない」の下限
NORMAL_COMBINED_THRESHOLD = 135   # ノーマル機の合算確率 設定6ライン (1/135)
NORMAL_MIN_G_COUNT = 2000         # ノーマル判定の最低ゲーム数

ZENTAI_WIN_RATE = 75.0            # 全台系の勝率閾値
ZENTAI_DIFF = 1000                # 全台系の差枚閾値
HANBUN_WIN_RATE = 50.0            # 半分系の勝率閾値
HANBUN_DIFF = 300                 # 半分系の差枚閾値


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class DeepGTag:
    """個別台の高設定タグ結果."""
    date: str
    machine_name: str
    unit_number: int
    g_count: int
    diff_payout: int
    bb_count: int
    rb_count: int
    tag: str  # "高設定濃厚" or "ノーマル優秀"
    combined_rate: float | None = None


@dataclass
class PinTendency:
    """ピン(単品)投入傾向の機種別集計."""
    machine_name: str
    high_setting_count: int = 0
    normal_excellent_count: int = 0
    total_pin_count: int = 0
    dates: list[str] = field(default_factory=list)
    avg_diff_when_tagged: float = 0.0
    frequent_units: list[int] = field(default_factory=list)


@dataclass
class LastDigitPerf:
    """台番号末尾ごとのパフォーマンス."""
    digit: int
    avg_diff_payout: float
    total_count: int
    win_rate: float


@dataclass
class RotationEntry:
    """全台系/半分系イベント."""
    date: str
    machine_name: str
    event_type: str  # "全台系" or "半分系"
    avg_diff_payout: float
    win_rate: float


@dataclass
class RotationPrediction:
    """ローテーション予測."""
    machine_name: str
    days_since_last: int
    avg_interval_days: float
    last_event_date: str
    event_count: int
    predicted_urgency: float  # 高いほど「順番が回ってきそう」


@dataclass
class OracleAdvice:
    """The Oracle: 統合狙い目アドバイス."""
    target_date: date
    date_label: str
    best_digit: int | None = None
    best_digit_diff: float = 0.0
    top_machines: list[dict] = field(default_factory=list)
    rotation_alerts: list[dict] = field(default_factory=list)
    pin_picks: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DeepGAnalyzer
# ---------------------------------------------------------------------------
class DeepGAnalyzer:
    """Deep-G-Analysis エンジン."""

    def __init__(
        self,
        db: SlotDatabase,
        alias_resolver: MachineAliasResolver | None = None,
    ) -> None:
        self._db = db
        self._alias = alias_resolver or MachineAliasResolver()

    # ------------------------------------------------------------------
    # データ読み込み
    # ------------------------------------------------------------------
    def _load_slot_data(self, shop_id: str) -> pd.DataFrame:
        rows = self._db.fetch_slot_data(shop_id=shop_id)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["machine_name"] = df["machine_name"].apply(self._alias.resolve)
        df["date"] = pd.to_datetime(df["date"])
        return df

    def _load_machine_stats(self, shop_id: str) -> pd.DataFrame:
        rows = self._db.fetch_machine_stats(shop_id=shop_id)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["machine_name"] = df["machine_name"].apply(self._alias.resolve)
        df["date"] = pd.to_datetime(df["date"])
        return df

    # ------------------------------------------------------------------
    # 1. Deep-G タグ付け
    # ------------------------------------------------------------------
    def analyze_deep_g(self, shop_id: str) -> list[DeepGTag]:
        """slot_data の各台を高設定タグで分類する."""
        df = self._load_slot_data(shop_id)
        if df.empty:
            return []

        tags: list[DeepGTag] = []
        for _, row in df.iterrows():
            g = int(row["g_count"])
            diff = int(row["diff_payout"])
            bb = int(row["bb_count"])
            rb = int(row["rb_count"])
            dt = row["date"].strftime("%Y-%m-%d")
            mname = row["machine_name"]
            unit = int(row["unit_number"])

            # 高設定濃厚: AT機 7000G以上 かつ 差枚が大きく凹んでいない
            if g >= AT_G_COUNT_THRESHOLD and diff >= HIGH_SETTING_DIFF_FLOOR:
                tags.append(DeepGTag(
                    date=dt, machine_name=mname, unit_number=unit,
                    g_count=g, diff_payout=diff, bb_count=bb, rb_count=rb,
                    tag="高設定濃厚",
                ))

            # ノーマル優秀: 合算確率が設定6相当以上
            total_bonus = bb + rb
            if total_bonus > 0 and g >= NORMAL_MIN_G_COUNT:
                combined = g / total_bonus
                if combined <= NORMAL_COMBINED_THRESHOLD:
                    # 高設定濃厚と重複しない場合のみ追加
                    already_tagged = (
                        g >= AT_G_COUNT_THRESHOLD
                        and diff >= HIGH_SETTING_DIFF_FLOOR
                    )
                    if not already_tagged:
                        tags.append(DeepGTag(
                            date=dt, machine_name=mname, unit_number=unit,
                            g_count=g, diff_payout=diff, bb_count=bb, rb_count=rb,
                            tag="ノーマル優秀", combined_rate=round(combined, 1),
                        ))

        return tags

    # ------------------------------------------------------------------
    # 2. ピン投入傾向の集計
    # ------------------------------------------------------------------
    def aggregate_pin_tendency(self, tags: list[DeepGTag]) -> list[PinTendency]:
        """機種ごとにピン投入傾向を集計する."""
        buckets: dict[str, list[DeepGTag]] = defaultdict(list)
        for t in tags:
            buckets[t.machine_name].append(t)

        tendencies: list[PinTendency] = []
        for name, items in buckets.items():
            high_ct = sum(1 for t in items if t.tag == "高設定濃厚")
            normal_ct = sum(1 for t in items if t.tag == "ノーマル優秀")
            dates = sorted(set(t.date for t in items))
            avg_diff = sum(t.diff_payout for t in items) / len(items)

            unit_freq: dict[int, int] = defaultdict(int)
            for t in items:
                unit_freq[t.unit_number] += 1
            top_units = sorted(unit_freq, key=lambda u: unit_freq[u], reverse=True)[:5]

            tendencies.append(PinTendency(
                machine_name=name,
                high_setting_count=high_ct,
                normal_excellent_count=normal_ct,
                total_pin_count=len(items),
                dates=dates,
                avg_diff_when_tagged=round(avg_diff),
                frequent_units=top_units,
            ))

        tendencies.sort(key=lambda t: t.total_pin_count, reverse=True)
        return tendencies

    # ------------------------------------------------------------------
    # 3. 末尾パフォーマンス分析
    # ------------------------------------------------------------------
    def analyze_last_digit(self, shop_id: str) -> list[LastDigitPerf]:
        """台番号末尾 (0-9) ごとの差枚パフォーマンスを分析する."""
        df = self._load_slot_data(shop_id)
        if df.empty:
            return []

        df["last_digit"] = df["unit_number"] % 10
        results: list[LastDigitPerf] = []

        for digit in range(10):
            ddf = df[df["last_digit"] == digit]
            if ddf.empty:
                continue
            avg_diff = float(ddf["diff_payout"].mean())
            total = len(ddf)
            wins = int((ddf["diff_payout"] > 0).sum())
            wr = wins / total * 100 if total > 0 else 0.0
            results.append(LastDigitPerf(
                digit=digit,
                avg_diff_payout=round(avg_diff),
                total_count=total,
                win_rate=round(wr, 1),
            ))

        return results

    # ------------------------------------------------------------------
    # 4. ローテーション分析
    # ------------------------------------------------------------------
    def analyze_rotation(
        self, shop_id: str,
    ) -> tuple[list[RotationEntry], list[RotationPrediction]]:
        """全台系/半分系のローテーション検出と次回予測."""
        ms_df = self._load_machine_stats(shop_id)
        if ms_df.empty:
            return [], []

        events: list[RotationEntry] = []
        for _, row in ms_df.iterrows():
            wr = float(row["win_rate"])
            diff = float(row["avg_diff_payout"])
            dt_val = row["date"]
            dt_str = (
                dt_val.strftime("%Y-%m-%d")
                if hasattr(dt_val, "strftime")
                else str(dt_val)[:10]
            )

            if wr >= ZENTAI_WIN_RATE and diff >= ZENTAI_DIFF:
                etype = "全台系"
            elif wr >= HANBUN_WIN_RATE and diff >= HANBUN_DIFF:
                etype = "半分系"
            else:
                continue

            events.append(RotationEntry(
                date=dt_str, machine_name=row["machine_name"],
                event_type=etype, avg_diff_payout=diff, win_rate=wr,
            ))

        # ローテーション予測
        today = date.today()
        machine_events: dict[str, list[RotationEntry]] = defaultdict(list)
        for e in events:
            machine_events[e.machine_name].append(e)

        predictions: list[RotationPrediction] = []
        for name, evts in machine_events.items():
            evts_sorted = sorted(evts, key=lambda e: e.date)
            dates = [date.fromisoformat(e.date) for e in evts_sorted]
            last_date = dates[-1]
            days_since = (today - last_date).days

            if len(dates) >= 2:
                intervals = [
                    (dates[i + 1] - dates[i]).days
                    for i in range(len(dates) - 1)
                ]
                avg_interval = sum(intervals) / len(intervals)
            else:
                avg_interval = 30.0

            urgency = days_since / avg_interval if avg_interval > 0 else 0

            predictions.append(RotationPrediction(
                machine_name=name,
                days_since_last=days_since,
                avg_interval_days=round(avg_interval, 1),
                last_event_date=evts_sorted[-1].date,
                event_count=len(evts),
                predicted_urgency=round(urgency, 2),
            ))

        predictions.sort(key=lambda p: p.predicted_urgency, reverse=True)
        return events, predictions

    # ------------------------------------------------------------------
    # 5. ローテーション・ヒートマップ用データ生成
    # ------------------------------------------------------------------
    def build_rotation_heatmap_data(
        self, events: list[RotationEntry],
    ) -> pd.DataFrame:
        """ローテーションイベントをヒートマップ用 DataFrame に変換."""
        if not events:
            return pd.DataFrame()

        rows = []
        for e in events:
            val = 2 if e.event_type == "全台系" else 1
            rows.append({
                "date": e.date,
                "machine_name": e.machine_name,
                "value": val,
                "event_type": e.event_type,
                "avg_diff": e.avg_diff_payout,
            })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df

    # ------------------------------------------------------------------
    # 6. The Oracle — 統合狙い目アドバイス
    # ------------------------------------------------------------------
    def generate_oracle(
        self,
        shop_id: str,
        tsumo_ranks: dict,
        target_date: date | None = None,
        day_suffix_targets: list[int] | None = None,
    ) -> OracleAdvice:
        """全分析を統合して狙い目アドバイスを生成する."""
        from utils.date_helper import get_date_attributes

        if target_date is None:
            target_date = date.today() + timedelta(days=1)

        attrs = get_date_attributes(target_date)
        suffix = attrs["day_suffix"]
        dow = attrs["day_of_week"]
        dow_names = ["月", "火", "水", "木", "金", "土", "日"]

        # 日付ラベル生成
        labels = [f"{dow_names[dow]}曜日", f"末尾{suffix}の日"]
        if attrs["is_zoro"]:
            labels.append("ゾロ目")
        if attrs["is_holiday"]:
            labels.append(f"祝日({attrs['holiday_name']})")
        is_target_day = day_suffix_targets and suffix in day_suffix_targets
        if is_target_day:
            labels.append("★特定日")
        date_label = " / ".join(labels)

        # 末尾分析
        digit_perfs = self.analyze_last_digit(shop_id)
        best_digit = None
        best_digit_diff = 0.0
        if digit_perfs:
            best = max(digit_perfs, key=lambda d: d.avg_diff_payout)
            best_digit = best.digit
            best_digit_diff = best.avg_diff_payout

        # Tsumo-Rank から当日の推奨機種
        top_machines = []
        suffix_ranks = tsumo_ranks.get(str(suffix), tsumo_ranks.get(suffix, []))
        for r in suffix_ranks[:5]:
            name = r["machine_name"] if isinstance(r, dict) else r.machine_name
            score = r["score"] if isinstance(r, dict) else r.score
            avg_diff = r["avg_diff_payout"] if isinstance(r, dict) else r.avg_diff_payout
            top_machines.append({
                "name": name, "score": score, "avg_diff": avg_diff,
                "reason": f"{suffix}の日 Tsumo-Rank上位",
            })

        # ローテーション予測
        _, predictions = self.analyze_rotation(shop_id)
        rotation_alerts = []
        for p in predictions[:5]:
            if p.predicted_urgency >= 0.8:
                rotation_alerts.append({
                    "name": p.machine_name,
                    "days_since": p.days_since_last,
                    "avg_interval": p.avg_interval_days,
                    "urgency": p.predicted_urgency,
                })

        # ピン投入傾向
        deep_tags = self.analyze_deep_g(shop_id)
        pin_tendencies = self.aggregate_pin_tendency(deep_tags)
        pin_picks = []
        for pt in pin_tendencies[:3]:
            if pt.total_pin_count >= 2:
                pin_picks.append({
                    "name": pt.machine_name,
                    "count": pt.total_pin_count,
                    "units": pt.frequent_units[:3],
                    "avg_diff": pt.avg_diff_when_tagged,
                })

        return OracleAdvice(
            target_date=target_date,
            date_label=date_label,
            best_digit=best_digit,
            best_digit_diff=best_digit_diff,
            top_machines=top_machines,
            rotation_alerts=rotation_alerts,
            pin_picks=pin_picks,
        )
