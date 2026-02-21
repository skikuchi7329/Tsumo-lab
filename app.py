"""Tsumo-Lab Web — 実戦特化型ダッシュボード.

機能:
  1. データインポーター: サイドバーから期間・店舗を指定してスクレイピング
  2. Deep-G-Analysis: 7000G稼働台の高設定タグ付け & ノーマル優秀判定
  3. ローテーション & 末尾推測ビュー: 末尾棒グラフ + ヒートマップ + 予測
  4. The Oracle: 全分析統合の狙い目サマリー

起動: streamlit run app.py  または  python main.py dashboard
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml

# プロジェクトルートを sys.path に追加
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analysis.deep_g_analyzer import (
    DeepGAnalyzer,
    DeepGTag,
    OracleAdvice,
    PinTendency,
)
from analysis.trend_analyzer import (
    AnalysisResult,
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
    return {s["shop_id"]: s for s in config.get("shops", [])}


@st.cache_data(ttl=300)
def _run_analysis(shop_id: str) -> dict:
    db = SlotDatabase()
    try:
        analyzer = TrendAnalyzer(db)
        result = analyzer.analyze(shop_id)
    finally:
        db.close()
    return _result_to_dict(result)


@st.cache_data(ttl=300)
def _fetch_daily_stats(shop_id: str) -> pd.DataFrame:
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


@st.cache_data(ttl=300)
def _run_deep_g(shop_id: str) -> dict:
    """Deep-G-Analysis を実行しキャッシュする."""
    db = SlotDatabase()
    try:
        dga = DeepGAnalyzer(db)
        tags = dga.analyze_deep_g(shop_id)
        pin_tendencies = dga.aggregate_pin_tendency(tags)
        digit_perfs = dga.analyze_last_digit(shop_id)
        events, predictions = dga.analyze_rotation(shop_id)
        heatmap_df = dga.build_rotation_heatmap_data(events)
    finally:
        db.close()
    return {
        "tags": [asdict(t) for t in tags],
        "pin_tendencies": [asdict(p) for p in pin_tendencies],
        "digit_perfs": [asdict(d) for d in digit_perfs],
        "events": [asdict(e) for e in events],
        "predictions": [asdict(p) for p in predictions],
        "heatmap_df": heatmap_df.to_dict("records") if not heatmap_df.empty else [],
    }


@st.cache_data(ttl=300)
def _run_oracle(
    shop_id: str,
    tsumo_ranks: dict,
    target_date_str: str,
    day_suffix_targets: list[int] | None,
) -> dict:
    """The Oracle アドバイスを生成しキャッシュする."""
    db = SlotDatabase()
    try:
        dga = DeepGAnalyzer(db)
        target = date.fromisoformat(target_date_str)
        advice = dga.generate_oracle(
            shop_id, tsumo_ranks, target, day_suffix_targets,
        )
    finally:
        db.close()
    return asdict(advice)


def _result_to_dict(result: AnalysisResult) -> dict:
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
    if not ranks:
        return pd.DataFrame()
    df = pd.DataFrame(ranks)
    df = df.rename(columns={
        "machine_name": "機種", "score": "スコア",
        "avg_diff_payout": "平均差枚", "avg_win_rate": "勝率(%)",
        "zentai_count": "全台系", "data_count": "データ数",
    })
    return df


def _trends_to_df(trends: list[dict]) -> pd.DataFrame:
    if not trends:
        return pd.DataFrame()
    df = pd.DataFrame(trends)
    df = df.rename(columns={
        "machine_name": "機種", "count": "日数",
        "avg_diff_payout": "平均差枚", "avg_win_rate": "勝率(%)",
        "avg_payout_rate": "出率(%)", "avg_g_count": "平均G数",
        "zentai_count": "全台系", "zentai_dates": "全台系実績日",
    })
    return df


# ---------------------------------------------------------------------------
# Plotly チャート
# ---------------------------------------------------------------------------
def _tsumo_rank_chart(ranks_df: pd.DataFrame, top_n: int = 15) -> go.Figure:
    df = ranks_df.head(top_n).copy()
    df = df.iloc[::-1]
    colors = ["#e74c3c" if v >= 0 else "#3498db" for v in df["平均差枚"]]
    fig = go.Figure(go.Bar(
        x=df["スコア"], y=df["機種"], orientation="h",
        marker_color=colors,
        text=df["スコア"].apply(lambda v: f"{v:,.0f}"),
        textposition="outside",
    ))
    fig.update_layout(
        title="Tsumo-Rank", xaxis_title="スコア", yaxis_title="",
        height=max(400, top_n * 32),
        margin=dict(l=10, r=10, t=40, b=30),
    )
    return fig


def _daily_diff_chart(df: pd.DataFrame, machine_name: str) -> go.Figure:
    mdf = df[df["machine_name"] == machine_name].sort_values("date")
    if mdf.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{machine_name} -- データなし")
        return fig
    fig = px.line(
        mdf, x="date", y="avg_diff_payout", markers=True,
        title=f"{machine_name} -- 日別 平均差枚推移",
        labels={"date": "日付", "avg_diff_payout": "平均差枚"},
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=40, b=30))
    return fig


def _last_digit_bar_chart(digit_perfs: list[dict]) -> go.Figure:
    """末尾パフォーマンス棒グラフ."""
    if not digit_perfs:
        return go.Figure()
    df = pd.DataFrame(digit_perfs)
    colors = ["#e74c3c" if v >= 0 else "#3498db" for v in df["avg_diff_payout"]]
    fig = go.Figure(go.Bar(
        x=df["digit"].astype(str),
        y=df["avg_diff_payout"],
        marker_color=colors,
        text=df["avg_diff_payout"].apply(lambda v: f"{v:+,.0f}"),
        textposition="outside",
    ))
    fig.update_layout(
        title="台番号末尾別 平均差枚",
        xaxis_title="末尾番号", yaxis_title="平均差枚",
        height=400, margin=dict(l=10, r=10, t=40, b=30),
    )
    return fig


def _rotation_heatmap(heatmap_records: list[dict]) -> go.Figure:
    """ローテーション・ヒートマップ."""
    if not heatmap_records:
        return go.Figure()
    df = pd.DataFrame(heatmap_records)
    df["date"] = pd.to_datetime(df["date"])

    machines = sorted(df["machine_name"].unique())
    dates = sorted(df["date"].unique())

    pivot = df.pivot_table(
        index="machine_name", columns="date", values="value",
        aggfunc="max", fill_value=0,
    )
    pivot = pivot.reindex(index=machines, fill_value=0)

    # カスタムカラースケール: 0=白, 1=黄(半分系), 2=赤(全台系)
    colorscale = [
        [0, "#f8f9fa"], [0.25, "#f8f9fa"],
        [0.25, "#ffc107"], [0.5, "#ffc107"],
        [0.5, "#ffc107"], [0.75, "#ffc107"],
        [0.75, "#dc3545"], [1.0, "#dc3545"],
    ]

    date_strs = [d.strftime("%m/%d") if hasattr(d, "strftime")
                 else pd.Timestamp(d).strftime("%m/%d") for d in pivot.columns]

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=date_strs,
        y=pivot.index.tolist(),
        colorscale=colorscale,
        zmin=0, zmax=2,
        showscale=False,
        hovertemplate="機種: %{y}<br>日付: %{x}<br>%{text}<extra></extra>",
        text=[
            ["全台系" if v == 2 else "半分系" if v == 1 else ""
             for v in row]
            for row in pivot.values
        ],
    ))
    fig.update_layout(
        title="ローテーション・ヒートマップ (赤=全台系 / 黄=半分系)",
        xaxis_title="日付", yaxis_title="",
        height=max(400, len(machines) * 24),
        margin=dict(l=10, r=10, t=40, b=30),
    )
    return fig


# ---------------------------------------------------------------------------
# KPI カード
# ---------------------------------------------------------------------------
def _render_kpi(trends: list[dict]) -> None:
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
# The Oracle 描画
# ---------------------------------------------------------------------------
def _render_oracle(oracle_data: dict) -> None:
    """The Oracle: 狙い目サマリーを最上部に描画."""
    target = oracle_data.get("target_date")
    if isinstance(target, str):
        target = date.fromisoformat(target)
    label = oracle_data.get("date_label", "")

    st.markdown("### The Oracle -- 狙い目サマリー")
    st.markdown(f"**対象日: {target}** ({label})")

    # メイン推奨
    cols = st.columns([1, 1, 1])

    best_digit = oracle_data.get("best_digit")
    if best_digit is not None:
        cols[0].metric(
            "狙い末尾",
            f"末尾 {best_digit}",
            f"平均差枚 {oracle_data.get('best_digit_diff', 0):+,.0f}",
        )
    else:
        cols[0].metric("狙い末尾", "データ不足", "")

    top_machines = oracle_data.get("top_machines", [])
    if top_machines:
        top = top_machines[0]
        cols[1].metric(
            "注目機種",
            top["name"],
            f"スコア {top['score']:,.0f} / 差枚 {top['avg_diff']:+,.0f}",
        )
    else:
        cols[1].metric("注目機種", "データ不足", "")

    rotation_alerts = oracle_data.get("rotation_alerts", [])
    if rotation_alerts:
        ra = rotation_alerts[0]
        cols[2].metric(
            "ローテーション警報",
            ra["name"],
            f"{ra['days_since']}日経過 (平均{ra['avg_interval']:.0f}日周期)",
        )
    else:
        cols[2].metric("ローテーション警報", "検出なし", "")

    # 詳細リスト
    with st.expander("詳細アドバイス"):
        if top_machines:
            st.markdown("**Tsumo-Rank 推奨機種:**")
            for i, m in enumerate(top_machines[:5], 1):
                st.markdown(
                    f"{i}. **{m['name']}** — "
                    f"スコア {m['score']:,.0f} / "
                    f"平均差枚 {m['avg_diff']:+,.0f} "
                    f"({m['reason']})"
                )

        pin_picks = oracle_data.get("pin_picks", [])
        if pin_picks:
            st.markdown("**ピン投入で狙える台番号:**")
            for pp in pin_picks:
                units_str = ", ".join(str(u) for u in pp["units"])
                st.markdown(
                    f"- **{pp['name']}**: "
                    f"過去{pp['count']}回検出 / "
                    f"平均差枚 {pp['avg_diff']:+,.0f} / "
                    f"よく使われる台番号: {units_str}"
                )

        if rotation_alerts:
            st.markdown("**ローテーション要注意:**")
            for ra in rotation_alerts:
                st.markdown(
                    f"- **{ra['name']}**: "
                    f"{ra['days_since']}日前が最後 "
                    f"(平均{ra['avg_interval']:.0f}日間隔, "
                    f"緊急度 {ra['urgency']:.1f}x)"
                )

    st.divider()


# ---------------------------------------------------------------------------
# Deep-G-Analysis 描画
# ---------------------------------------------------------------------------
def _render_deep_g_tab(deep_data: dict) -> None:
    """Deep-G-Analysis タブの描画."""
    tags = deep_data.get("tags", [])
    pin_tendencies = deep_data.get("pin_tendencies", [])

    if not tags:
        st.info(
            "Deep-G データがありません。先にデータをインポートしてください。"
        )
        return

    # サマリーカード
    high_count = sum(1 for t in tags if t["tag"] == "高設定濃厚")
    normal_count = sum(1 for t in tags if t["tag"] == "ノーマル優秀")
    unique_machines = len(set(t["machine_name"] for t in tags))
    unique_dates = len(set(t["date"] for t in tags))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("高設定濃厚", f"{high_count} 台")
    c2.metric("ノーマル優秀", f"{normal_count} 台")
    c3.metric("対象機種数", f"{unique_machines}")
    c4.metric("検出日数", f"{unique_dates}")

    # タグ別テーブル
    tag_filter = st.radio(
        "フィルター", ["すべて", "高設定濃厚", "ノーマル優秀"],
        horizontal=True, key="deep_g_filter",
    )
    filtered = tags
    if tag_filter != "すべて":
        filtered = [t for t in tags if t["tag"] == tag_filter]

    if filtered:
        df = pd.DataFrame(filtered)
        df = df.rename(columns={
            "date": "日付", "machine_name": "機種",
            "unit_number": "台番号", "g_count": "G数",
            "diff_payout": "差枚", "bb_count": "BB",
            "rb_count": "RB", "tag": "タグ",
            "combined_rate": "合算確率",
        })
        display_cols = ["日付", "機種", "台番号", "G数", "差枚", "BB", "RB", "タグ"]
        if tag_filter == "ノーマル優秀" or tag_filter == "すべて":
            display_cols.append("合算確率")
        df_display = df[display_cols].sort_values(
            ["日付", "機種"], ascending=[False, True],
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)

    # ピン投入傾向
    st.subheader("ピン投入傾向 (機種別)")
    if pin_tendencies:
        pin_df = pd.DataFrame(pin_tendencies)
        pin_df = pin_df.rename(columns={
            "machine_name": "機種",
            "high_setting_count": "高設定濃厚",
            "normal_excellent_count": "ノーマル優秀",
            "total_pin_count": "合計検出",
            "dates": "検出日",
            "avg_diff_when_tagged": "平均差枚",
            "frequent_units": "常連台番号",
        })
        pin_df["検出日"] = pin_df["検出日"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else str(v)
        )
        pin_df["常連台番号"] = pin_df["常連台番号"].apply(
            lambda v: ", ".join(str(u) for u in v) if isinstance(v, list) else str(v)
        )
        st.dataframe(pin_df, use_container_width=True, hide_index=True)
    else:
        st.info("ピン投入データなし")


# ---------------------------------------------------------------------------
# ローテーション & 末尾タブ描画
# ---------------------------------------------------------------------------
def _render_rotation_tab(deep_data: dict) -> None:
    """ローテーション & 末尾推測ビュータブ."""
    digit_perfs = deep_data.get("digit_perfs", [])
    events = deep_data.get("events", [])
    predictions = deep_data.get("predictions", [])
    heatmap_records = deep_data.get("heatmap_df", [])

    # --- 末尾集計 ---
    st.subheader("末尾パフォーマンス")
    if digit_perfs:
        st.plotly_chart(
            _last_digit_bar_chart(digit_perfs), use_container_width=True,
        )
        digit_df = pd.DataFrame(digit_perfs).rename(columns={
            "digit": "末尾", "avg_diff_payout": "平均差枚",
            "total_count": "サンプル数", "win_rate": "勝率(%)",
        })
        st.dataframe(digit_df, use_container_width=True, hide_index=True)
    else:
        st.info("末尾データなし")

    st.divider()

    # --- ローテーション・ヒートマップ ---
    st.subheader("ローテーション・ヒートマップ")
    if heatmap_records:
        st.plotly_chart(
            _rotation_heatmap(heatmap_records), use_container_width=True,
        )
    else:
        st.info("ローテーションイベントなし")

    # --- ローテーション予測テーブル ---
    st.subheader("ローテーション予測 -- 順番が来そうな機種")
    if predictions:
        pred_df = pd.DataFrame(predictions).rename(columns={
            "machine_name": "機種",
            "days_since_last": "最終イベントからの日数",
            "avg_interval_days": "平均周期(日)",
            "last_event_date": "最終イベント日",
            "event_count": "イベント回数",
            "predicted_urgency": "緊急度",
        })
        # 緊急度で色分け表示のための列追加
        pred_df = pred_df.sort_values("緊急度", ascending=False)
        st.dataframe(pred_df, use_container_width=True, hide_index=True)
    else:
        st.info("予測データなし")

    # --- イベント履歴 ---
    with st.expander("全台系/半分系イベント履歴"):
        if events:
            ev_df = pd.DataFrame(events).rename(columns={
                "date": "日付", "machine_name": "機種",
                "event_type": "種別", "avg_diff_payout": "平均差枚",
                "win_rate": "勝率(%)",
            })
            ev_df = ev_df.sort_values("日付", ascending=False)
            st.dataframe(ev_df, use_container_width=True, hide_index=True)
        else:
            st.info("イベントなし")


# ---------------------------------------------------------------------------
# トレンド分析タブ描画 (既存ロジック統合)
# ---------------------------------------------------------------------------
def _render_trend_tab(
    data: dict, score_min: float, day_suffix_choice: int | None,
    analysis_type: str, daily_df: pd.DataFrame,
) -> None:
    """既存のトレンド分析セクション."""
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

    # 機種詳細
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
        mdf = daily_df[daily_df["machine_name"] == selected_machine]
        if not mdf.empty:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("データ日数", f"{len(mdf)}日")
            c2.metric("平均差枚", f"{mdf['avg_diff_payout'].mean():+,.0f}")
            c3.metric("平均勝率", f"{mdf['win_rate'].mean():.1f}%")
            c4.metric("平均出率", f"{mdf['payout_rate'].mean():.1f}%")


def _render_day_suffix_section(
    data: dict, score_min: float, day_suffix: int | None,
) -> None:
    suffixes = (
        [day_suffix] if day_suffix is not None
        else sorted(data["tsumo_ranks"].keys())
    )
    for s_key in suffixes:
        s = int(s_key)
        ranks = data["tsumo_ranks"].get(str(s), data["tsumo_ranks"].get(s, []))
        trends = data["day_suffix_trends"].get(
            str(s), data["day_suffix_trends"].get(s, []),
        )
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
        st.plotly_chart(
            _tsumo_rank_chart(ranks_df), use_container_width=True,
        )
        with st.expander("実績詳細テーブル"):
            trends_df = _trends_to_df(trends)
            if score_min > 0:
                top_machines = set(ranks_df["機種"])
                trends_df = trends_df[trends_df["機種"].isin(top_machines)]
            _render_trends_table(trends_df)


def _render_zoro_section(data: dict, score_min: float) -> None:
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
        st.plotly_chart(
            _tsumo_rank_chart(ranks_df), use_container_width=True,
        )
    with st.expander("実績詳細テーブル"):
        _render_trends_table(_trends_to_df(trends))


def _render_weekday_section(data: dict, score_min: float) -> None:
    weekday_trends = data.get("weekday_trends", {})
    if not weekday_trends:
        st.info("曜日別データがありません。")
        return
    tabs = st.tabs([f"{_DOW_NAMES[i]}曜" for i in range(7)])
    for dow in range(7):
        with tabs[dow]:
            trends = weekday_trends.get(
                str(dow), weekday_trends.get(dow, []),
            )
            if not trends:
                st.info(f"{_DOW_NAMES[dow]}曜日のデータがありません。")
                continue
            _render_kpi(trends)
            trends_df = _trends_to_df(trends)
            if score_min > 0:
                trends_df = trends_df[trends_df["平均差枚"] >= score_min]
            _render_trends_table(trends_df)


def _render_post_holiday_section(data: dict, score_min: float) -> None:
    trends = data.get("post_holiday_trends", [])
    if not trends:
        st.info("新装開店データがありません。")
        return
    st.subheader("新装開店 (前日データなし)")
    _render_kpi(trends)
    _render_trends_table(_trends_to_df(trends))


def _render_holiday_section(data: dict, score_min: float) -> None:
    trends = data.get("holiday_trends", [])
    if not trends:
        st.info("祝日データがありません。")
        return
    st.subheader("祝日")
    _render_kpi(trends)
    _render_trends_table(_trends_to_df(trends))


def _render_trends_table(df: pd.DataFrame) -> None:
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
# データインポーター
# ---------------------------------------------------------------------------
def _render_data_importer(config: dict) -> None:
    """サイドバーのデータインポーター."""
    st.header("データインポート")

    all_shop_names = [s["name"] for s in config.get("shops", [])]

    import_shop = st.text_input(
        "店舗名",
        value=all_shop_names[0] if all_shop_names else "",
        help="config.yaml に登録済みの店舗名 or 新規店舗名",
    )
    import_days = st.number_input(
        "取得日数",
        min_value=1, max_value=180, value=30,
    )

    if st.button("スクレイピング開始", type="primary", use_container_width=True):
        if not import_shop.strip():
            st.error("店舗名を入力してください。")
            return

        with st.spinner(f"「{import_shop}」のデータを取得中..."):
            try:
                cmd = [
                    sys.executable, str(ROOT_DIR / "main.py"),
                    "scrape",
                    "--shop-name", import_shop.strip(),
                    "--days", str(import_days),
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    cwd=str(ROOT_DIR),
                )
                if result.returncode == 0:
                    st.success(
                        f"「{import_shop}」のデータ取得が完了しました。"
                    )
                    # キャッシュクリア
                    st.cache_data.clear()
                else:
                    st.error("スクレイピングでエラーが発生しました。")
                    with st.expander("エラー詳細"):
                        st.code(result.stderr or result.stdout)
            except subprocess.TimeoutExpired:
                st.error("タイムアウトしました (10分)。日数を減らして再試行してください。")
            except Exception as e:
                st.error(f"エラー: {e}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Tsumo-Lab",
        page_icon="🎰",
        layout="wide",
    )

    st.title("Tsumo-Lab")
    st.caption("実戦特化型パチスロ傾向分析ダッシュボード")

    config = _load_config()
    shop_map = _build_shop_map(config)

    if not shop_map:
        st.error("config.yaml に店舗が定義されていません。")
        return

    # =================================================================
    # サイドバー
    # =================================================================
    with st.sidebar:
        # --- データインポーター ---
        _render_data_importer(config)

        st.divider()

        # --- フィルター設定 ---
        st.header("分析フィルター")

        shop_options = {
            cfg["name"]: sid for sid, cfg in shop_map.items()
        }
        selected_shop_name = st.selectbox(
            "店舗", options=list(shop_options.keys()),
        )
        selected_shop_id = shop_options[selected_shop_name]
        shop_cfg = shop_map.get(selected_shop_id, {})

        # トレンド分析タイプ
        selected_type_label = st.selectbox(
            "トレンド分析タイプ",
            options=list(ANALYSIS_TYPES.keys()),
        )
        analysis_type = ANALYSIS_TYPES[selected_type_label]

        day_suffix_choice = None
        if analysis_type == "day_suffix":
            suffix_options = ["すべて"] + [str(i) for i in range(10)]
            suffix_sel = st.selectbox("日の 1 の位", options=suffix_options)
            if suffix_sel != "すべて":
                day_suffix_choice = int(suffix_sel)

        score_min = st.slider(
            "最小 Tsumo-Rank スコア",
            min_value=0, max_value=3000, value=0, step=50,
        )

        # Oracle の対象日
        st.divider()
        st.header("The Oracle 設定")
        oracle_date = st.date_input(
            "狙い目の対象日",
            value=date.today() + timedelta(days=1),
        )

        st.divider()
        st.caption(f"店舗ID: {selected_shop_id}")

    # =================================================================
    # 分析実行 (キャッシュ)
    # =================================================================
    with st.spinner("分析中..."):
        data = _run_analysis(selected_shop_id)
        daily_df = _fetch_daily_stats(selected_shop_id)
        deep_data = _run_deep_g(selected_shop_id)

    if not data:
        st.warning(
            "分析データがありません。サイドバーの「データインポート」で "
            "データを取得してください。"
        )
        return

    # =================================================================
    # The Oracle (最上部)
    # =================================================================
    day_suffix_targets = shop_cfg.get("day_suffix_targets")
    oracle_data = _run_oracle(
        selected_shop_id,
        data.get("tsumo_ranks", {}),
        oracle_date.isoformat(),
        day_suffix_targets,
    )
    _render_oracle(oracle_data)

    # =================================================================
    # メインタブ
    # =================================================================
    tab_deep, tab_rotation, tab_trend = st.tabs([
        "Deep-G 分析",
        "ローテーション & 末尾",
        "トレンド分析",
    ])

    with tab_deep:
        _render_deep_g_tab(deep_data)

    with tab_rotation:
        _render_rotation_tab(deep_data)

    with tab_trend:
        _render_trend_tab(
            data, score_min, day_suffix_choice,
            analysis_type, daily_df,
        )


if __name__ == "__main__":
    main()
