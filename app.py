"""Tsumo-Lab Web — Streamlit ダッシュボード.

TrendAnalyzer の分析結果を可視化するインタラクティブ・ダッシュボード。
起動: streamlit run app.py  または  python main.py dashboard
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

# プロジェクトルートを sys.path に追加 (streamlit run 時のインポート解決)
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analysis.trend_analyzer import (
    AnalysisResult,
    MachineTrend,
    TrendAnalyzer,
    TsumoRank,
)
from database.db_handler import SlotDatabase

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
CONFIG_PATH = ROOT_DIR / "config" / "config.yaml"
_DOW_NAMES = ["月", "火", "水", "木", "金", "土", "日"]

ANALYSIS_TYPES = {
    "特定日": "day_suffix",
    "ゾロ目": "zoro",
    "曜日": "weekday",
    "新装開店": "post_holiday",
    "祝日": "holiday",
}


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------
def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_shop_map(config: dict) -> dict[str, dict]:
    """shop_id → shop config の辞書を構築する."""
    return {s["shop_id"]: s for s in config.get("shops", [])}


@st.cache_data(ttl=300)
def _run_analysis(shop_id: str) -> dict:
    """TrendAnalyzer で分析を実行し、結果を辞書化して返す (キャッシュ対象)."""
    db = SlotDatabase()
    try:
        analyzer = TrendAnalyzer(db)
        result = analyzer.analyze(shop_id)
    finally:
        db.close()
    return _result_to_dict(result)


@st.cache_data(ttl=300)
def _fetch_daily_stats(shop_id: str) -> pd.DataFrame:
    """指定店舗の machine_stats 全レコードを DataFrame で返す (キャッシュ対象)."""
    db = SlotDatabase()
    try:
        rows = db.fetch_machine_stats(shop_id=shop_id)
    finally:
        db.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _result_to_dict(result: AnalysisResult) -> dict:
    """AnalysisResult をシリアライズ可能な辞書に変換する."""
    return {
        "shop_id": result.shop_id,
        "day_suffix_trends": {
            k: [asdict(t) for t in v]
            for k, v in result.day_suffix_trends.items()
        },
        "zoro_trends": [asdict(t) for t in result.zoro_trends],
        "post_holiday_trends": [asdict(t) for t in result.post_holiday_trends],
        "weekday_trends": {
            k: [asdict(t) for t in v]
            for k, v in result.weekday_trends.items()
        },
        "holiday_trends": [asdict(t) for t in result.holiday_trends],
        "tsumo_ranks": {
            k: [asdict(r) for r in v]
            for k, v in result.tsumo_ranks.items()
        },
        "zoro_tsumo_ranks": [asdict(r) for r in result.zoro_tsumo_ranks],
    }


def _ranks_to_df(ranks: list[dict]) -> pd.DataFrame:
    """TsumoRank 辞書リストを表示用 DataFrame に変換する."""
    if not ranks:
        return pd.DataFrame()
    df = pd.DataFrame(ranks)
    df = df.rename(columns={
        "machine_name": "機種",
        "score": "スコア",
        "avg_diff_payout": "平均差枚",
        "avg_win_rate": "勝率(%)",
        "zentai_count": "全台系",
        "data_count": "データ数",
    })
    return df


def _trends_to_df(trends: list[dict]) -> pd.DataFrame:
    """MachineTrend 辞書リストを表示用 DataFrame に変換する."""
    if not trends:
        return pd.DataFrame()
    df = pd.DataFrame(trends)
    df = df.rename(columns={
        "machine_name": "機種",
        "count": "日数",
        "avg_diff_payout": "平均差枚",
        "avg_win_rate": "勝率(%)",
        "avg_payout_rate": "出率(%)",
        "avg_g_count": "平均G数",
        "zentai_count": "全台系",
        "zentai_dates": "全台系実績日",
    })
    return df


# ---------------------------------------------------------------------------
# Plotly チャート
# ---------------------------------------------------------------------------
def _tsumo_rank_chart(ranks_df: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """Tsumo-Rank 横棒グラフ (プラス差枚=赤 / マイナス=青)."""
    df = ranks_df.head(top_n).copy()
    df = df.iloc[::-1]  # 上位を上に表示
    colors = ["#e74c3c" if v >= 0 else "#3498db" for v in df["平均差枚"]]

    fig = go.Figure(go.Bar(
        x=df["スコア"],
        y=df["機種"],
        orientation="h",
        marker_color=colors,
        text=df["スコア"].apply(lambda v: f"{v:,.0f}"),
        textposition="outside",
    ))
    fig.update_layout(
        title="Tsumo-Rank",
        xaxis_title="スコア",
        yaxis_title="",
        height=max(400, top_n * 32),
        margin=dict(l=10, r=10, t=40, b=30),
    )
    return fig


def _daily_diff_chart(df: pd.DataFrame, machine_name: str) -> go.Figure:
    """指定機種の日別差枚推移ラインチャート."""
    mdf = df[df["machine_name"] == machine_name].sort_values("date")
    if mdf.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{machine_name} — データなし")
        return fig

    fig = px.line(
        mdf,
        x="date",
        y="avg_diff_payout",
        markers=True,
        title=f"{machine_name} — 日別 平均差枚推移",
        labels={"date": "日付", "avg_diff_payout": "平均差枚"},
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=40, b=30),
    )
    return fig


# ---------------------------------------------------------------------------
# KPI カード
# ---------------------------------------------------------------------------
def _render_kpi(trends: list[dict]) -> None:
    """KPI カード (総差枚・平均勝率・全台系発生率) を表示する."""
    if not trends:
        st.info("データがありません。")
        return

    total_diff = sum(t["avg_diff_payout"] * t["count"] for t in trends)
    total_days = sum(t["count"] for t in trends)
    avg_win = (
        sum(t["avg_win_rate"] * t["count"] for t in trends) / total_days
        if total_days else 0
    )
    zentai_total = sum(t["zentai_count"] for t in trends)
    zentai_rate = (zentai_total / len(trends) * 100) if trends else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("総差枚 (加重合計)", f"{total_diff:+,.0f} 枚")
    c2.metric("平均勝率", f"{avg_win:.1f}%")
    c3.metric("全台系発生率", f"{zentai_rate:.1f}% ({zentai_total}回 / {len(trends)}機種)")


# ---------------------------------------------------------------------------
# セクション描画
# ---------------------------------------------------------------------------
def _render_day_suffix_section(
    data: dict, score_min: float, day_suffix: int | None,
) -> None:
    """特定日セクション."""
    suffixes = [day_suffix] if day_suffix is not None else sorted(data["tsumo_ranks"].keys())

    for s_key in suffixes:
        s = int(s_key)
        ranks = data["tsumo_ranks"].get(str(s), data["tsumo_ranks"].get(s, []))
        trends = data["day_suffix_trends"].get(str(s), data["day_suffix_trends"].get(s, []))
        if not ranks:
            continue

        st.subheader(f"{s}の日")
        _render_kpi(trends)

        ranks_df = _ranks_to_df(ranks)
        if score_min > 0:
            ranks_df = ranks_df[ranks_df["スコア"] >= score_min]
        if ranks_df.empty:
            st.warning(f"スコア {score_min:.0f} 以上の機種はありません。")
            continue

        st.plotly_chart(_tsumo_rank_chart(ranks_df), use_container_width=True)

        with st.expander("実績詳細テーブル"):
            trends_df = _trends_to_df(trends)
            if score_min > 0:
                top_machines = set(ranks_df["機種"])
                trends_df = trends_df[trends_df["機種"].isin(top_machines)]
            _render_trends_table(trends_df)


def _render_zoro_section(data: dict, score_min: float) -> None:
    """ゾロ目セクション."""
    ranks = data.get("zoro_tsumo_ranks", [])
    trends = data.get("zoro_trends", [])
    if not ranks:
        st.info("ゾロ目日のデータがありません。")
        return

    st.subheader("ゾロ目の日")
    _render_kpi(trends)

    ranks_df = _ranks_to_df(ranks)
    if score_min > 0:
        ranks_df = ranks_df[ranks_df["スコア"] >= score_min]
    if not ranks_df.empty:
        st.plotly_chart(_tsumo_rank_chart(ranks_df), use_container_width=True)

    with st.expander("実績詳細テーブル"):
        _render_trends_table(_trends_to_df(trends))


def _render_weekday_section(data: dict, score_min: float) -> None:
    """曜日セクション."""
    weekday_trends = data.get("weekday_trends", {})
    if not weekday_trends:
        st.info("曜日別データがありません。")
        return

    tabs = st.tabs([f"{_DOW_NAMES[i]}曜" for i in range(7)])
    for dow in range(7):
        with tabs[dow]:
            trends = weekday_trends.get(str(dow), weekday_trends.get(dow, []))
            if not trends:
                st.info(f"{_DOW_NAMES[dow]}曜日のデータがありません。")
                continue

            _render_kpi(trends)
            trends_df = _trends_to_df(trends)
            if score_min > 0:
                trends_df = trends_df[trends_df["平均差枚"] >= score_min]
            _render_trends_table(trends_df)


def _render_post_holiday_section(data: dict, score_min: float) -> None:
    """新装開店セクション."""
    trends = data.get("post_holiday_trends", [])
    if not trends:
        st.info("新装開店データがありません。")
        return

    st.subheader("新装開店 (前日データなし)")
    _render_kpi(trends)

    trends_df = _trends_to_df(trends)
    _render_trends_table(trends_df)


def _render_holiday_section(data: dict, score_min: float) -> None:
    """祝日セクション."""
    trends = data.get("holiday_trends", [])
    if not trends:
        st.info("祝日データがありません。")
        return

    st.subheader("祝日")
    _render_kpi(trends)

    trends_df = _trends_to_df(trends)
    _render_trends_table(trends_df)


def _render_trends_table(df: pd.DataFrame) -> None:
    """MachineTrend の DataFrame を表示する. 全台系実績日は見やすく整形."""
    if df.empty:
        st.info("該当データなし")
        return

    display_df = df.copy()
    if "全台系実績日" in display_df.columns:
        display_df["全台系実績日"] = display_df["全台系実績日"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else str(v)
        )
    st.dataframe(display_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Tsumo-Lab Web",
        page_icon="🎰",
        layout="wide",
    )

    st.title("Tsumo-Lab Web")
    st.caption("パチスロ傾向分析ダッシュボード")

    # --- config 読み込み ---
    config = _load_config()
    shop_map = _build_shop_map(config)

    if not shop_map:
        st.error("config.yaml に店舗が定義されていません。")
        return

    # =================================================================
    # サイドバー
    # =================================================================
    with st.sidebar:
        st.header("フィルター設定")

        # 店舗選択
        shop_options = {
            cfg["name"]: sid for sid, cfg in shop_map.items()
        }
        selected_shop_name = st.selectbox(
            "店舗",
            options=list(shop_options.keys()),
        )
        selected_shop_id = shop_options[selected_shop_name]

        # 分析タイプ
        selected_type_label = st.selectbox(
            "分析タイプ",
            options=list(ANALYSIS_TYPES.keys()),
        )
        analysis_type = ANALYSIS_TYPES[selected_type_label]

        # 特定日の場合: 日の 1 の位を選択
        day_suffix_choice = None
        if analysis_type == "day_suffix":
            shop_cfg = shop_map.get(selected_shop_id, {})
            default_targets = shop_cfg.get("day_suffix_targets", [])
            suffix_options = ["すべて"] + [str(i) for i in range(10)]
            suffix_sel = st.selectbox("日の 1 の位", options=suffix_options)
            if suffix_sel != "すべて":
                day_suffix_choice = int(suffix_sel)

        # スコア閾値
        score_min = st.slider(
            "最小 Tsumo-Rank スコア",
            min_value=0,
            max_value=3000,
            value=0,
            step=50,
        )

        st.divider()
        st.caption(f"店舗ID: {selected_shop_id}")

    # =================================================================
    # 分析実行 (キャッシュ)
    # =================================================================
    with st.spinner("分析中..."):
        data = _run_analysis(selected_shop_id)
        daily_df = _fetch_daily_stats(selected_shop_id)

    if not data:
        st.warning("分析データがありません。先に `python main.py scrape` でデータを収集してください。")
        return

    # =================================================================
    # メイン: 分析タイプごとの表示
    # =================================================================
    if analysis_type == "day_suffix":
        _render_day_suffix_section(data, score_min, day_suffix_choice)
    elif analysis_type == "zoro":
        _render_zoro_section(data, score_min)
    elif analysis_type == "weekday":
        _render_weekday_section(data, score_min)
    elif analysis_type == "post_holiday":
        _render_post_holiday_section(data, score_min)
    elif analysis_type == "holiday":
        _render_holiday_section(data, score_min)

    # =================================================================
    # 機種詳細分析モード
    # =================================================================
    st.divider()
    st.subheader("機種詳細分析")

    if daily_df.empty:
        st.info("日別データがありません。")
        return

    machine_list = sorted(daily_df["machine_name"].unique())
    selected_machine = st.selectbox("機種を選択", options=machine_list)

    if selected_machine:
        st.plotly_chart(
            _daily_diff_chart(daily_df, selected_machine),
            use_container_width=True,
        )

        # 補足: 選択機種のサマリー
        mdf = daily_df[daily_df["machine_name"] == selected_machine]
        if not mdf.empty:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("データ日数", f"{len(mdf)}日")
            c2.metric("平均差枚", f"{mdf['avg_diff_payout'].mean():+,.0f}")
            c3.metric("平均勝率", f"{mdf['win_rate'].mean():.1f}%")
            c4.metric("平均出率", f"{mdf['payout_rate'].mean():.1f}%")


if __name__ == "__main__":
    main()
