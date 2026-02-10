"""日付属性を分析するユーティリティ.

パチスロホールの「強い日」判定に必要な各種フラグを算出する。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional, Sequence

import holidays

# ---------------------------------------------------------------------------
# 日本の祝日キャッシュ
# ---------------------------------------------------------------------------
_JP_HOLIDAYS: dict[int, holidays.Japan] = {}


def _get_jp_holidays(year: int) -> holidays.Japan:
    """指定年の日本祝日オブジェクトを取得する (キャッシュ付き)."""
    if year not in _JP_HOLIDAYS:
        _JP_HOLIDAYS[year] = holidays.Japan(years=year)
    return _JP_HOLIDAYS[year]


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------
def get_date_attributes(
    target_date: date,
    past_dates: Optional[Sequence[date]] = None,
) -> dict[str, Any]:
    """日付を分析し、分析属性を辞書で返す.

    Args:
        target_date: 分析対象の日付。
        past_dates: 過去にデータが存在する日付のリスト / セット。
            渡された場合、前日がこのリストに含まれていなければ
            ``is_post_holiday`` を ``True`` にする。
            ``None`` の場合は ``False`` を返す。

    Returns:
        dict with keys:
            - day_suffix (int): 日付の1の位 (0–9)
            - is_zoro (bool): ゾロ目の日 (11日, 22日 または 月 == 日)
            - day_of_week (int): 曜日 (0=月 .. 6=日)
            - is_holiday (bool): 祝日フラグ
            - holiday_name (str | None): 祝日名 (祝日でなければ None)
            - is_post_holiday (bool): 前日のデータが存在しない場合 True
    """
    day = target_date.day
    month = target_date.month

    # day_suffix: 日付の1の位
    day_suffix: int = day % 10

    # is_zoro: ゾロ目判定
    #   - 日の十の位と一の位が同じ (11, 22)
    #   - 月 == 日 (1/1, 2/2, 3/3, ... 9/9)
    tens = day // 10
    is_day_zoro = tens != 0 and tens == day_suffix
    is_month_eq_day = month == day
    is_zoro: bool = is_day_zoro or is_month_eq_day

    # day_of_week: 曜日 (0=月 .. 6=日)
    day_of_week: int = target_date.weekday()

    # is_holiday: 祝日判定
    jp_holidays = _get_jp_holidays(target_date.year)
    holiday_name: str | None = jp_holidays.get(target_date)
    is_holiday: bool = holiday_name is not None

    # is_post_holiday: 前日データが存在しなければ True
    is_post_holiday: bool = False
    if past_dates is not None:
        yesterday = target_date - timedelta(days=1)
        past_set = set(past_dates) if not isinstance(past_dates, set) else past_dates
        is_post_holiday = yesterday not in past_set

    return {
        "day_suffix": day_suffix,
        "is_zoro": is_zoro,
        "day_of_week": day_of_week,
        "is_holiday": is_holiday,
        "holiday_name": holiday_name,
        "is_post_holiday": is_post_holiday,
    }
