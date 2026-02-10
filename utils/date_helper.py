"""日付に関するユーティリティ関数."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import holidays

# 日本の祝日カレンダー (キャッシュして再利用)
_JP_HOLIDAYS: dict[int, holidays.Japan] = {}

WEEKDAY_NAMES_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _get_jp_holidays(year: int) -> holidays.Japan:
    """指定年の日本祝日オブジェクトを取得する (キャッシュ付き)."""
    if year not in _JP_HOLIDAYS:
        _JP_HOLIDAYS[year] = holidays.Japan(years=year)
    return _JP_HOLIDAYS[year]


@dataclass
class DateFlags:
    """日付フラグをまとめたデータクラス.

    Attributes:
        target_date: 対象日付
        ones_digit: 日付の1の位 (「Nのつく日」の N)
        n_tsuku_flag: Nのつく日フラグ — 日付の1の位が N であるか
        zorome_flag: ゾロ目フラグ (11日, 22日 など)
        weekday: 曜日 (0=月 .. 6=日)
        weekday_ja: 曜日の日本語表記
        is_holiday: 祝日であるか
        holiday_name: 祝日名 (祝日でなければ None)
        is_grand_opening: 新装開店フラグ (判定できない場合 None)
    """

    target_date: date
    ones_digit: int
    n_tsuku_flag: dict[int, bool]
    zorome_flag: bool
    weekday: int
    weekday_ja: str
    is_holiday: bool
    holiday_name: Optional[str]
    is_grand_opening: Optional[bool]


def analyze_date(
    target: date,
    grand_opening_dates: Optional[set[date]] = None,
) -> DateFlags:
    """日付を分析し、各種フラグを返す.

    Args:
        target: 分析対象の日付.
        grand_opening_dates: 新装開店の日付セット。渡されなければ
            is_grand_opening は None になる。

    Returns:
        DateFlags: 分析結果.
    """
    day = target.day
    ones_digit = day % 10

    # Nのつく日フラグ: 0-9 それぞれについて、日付の1の位が一致するか
    n_tsuku_flag = {n: (ones_digit == n) for n in range(10)}

    # ゾロ目フラグ: 11, 22 のように十の位と一の位が同じ
    tens_digit = day // 10
    zorome_flag = tens_digit != 0 and tens_digit == ones_digit

    # 曜日
    weekday = target.weekday()
    weekday_ja = WEEKDAY_NAMES_JA[weekday]

    # 祝日判定
    jp_holidays = _get_jp_holidays(target.year)
    holiday_name = jp_holidays.get(target)
    is_holiday = holiday_name is not None

    # 新装開店
    if grand_opening_dates is not None:
        is_grand_opening = target in grand_opening_dates
    else:
        is_grand_opening = None

    return DateFlags(
        target_date=target,
        ones_digit=ones_digit,
        n_tsuku_flag=n_tsuku_flag,
        zorome_flag=zorome_flag,
        weekday=weekday,
        weekday_ja=weekday_ja,
        is_holiday=is_holiday,
        holiday_name=holiday_name,
        is_grand_opening=is_grand_opening,
    )
