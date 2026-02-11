"""みんレポ特有の文字列 → 数値変換ヘルパー.

差枚・回転数などの数値フィールドを安全にパースするためのユーティリティ。
全角/半角・各種マイナス記号・カンマ・パーセント記号・空文字を考慮する。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# ---------------------------------------------------------------------------
# 内部: 正規化テーブル
# ---------------------------------------------------------------------------
# みんレポで使われうる各種マイナス記号を統一
_MINUS_CHARS = (
    "\u2212",  # −  MINUS SIGN
    "\u2013",  # –  EN DASH
    "\u2014",  # —  EM DASH
    "\u2015",  # ―  HORIZONTAL BAR
    "\u30FC",  # ー  KATAKANA-HIRAGANA PROLONGED SOUND MARK
    "\uFF0D",  # ＝ FULLWIDTH HYPHEN-MINUS
)

_PERCENT_RE = re.compile(r"[%％]")


def _normalize(value: str) -> str:
    """全角数字 → 半角、各種マイナス → ASCII ハイフン、カンマ除去."""
    # 全角 → 半角 (数字・ASCII 互換文字)
    text = unicodedata.normalize("NFKC", value)
    # 各種マイナス記号 → ASCII ハイフン
    for ch in _MINUS_CHARS:
        text = text.replace(ch, "-")
    # カンマ・プラス記号・空白を除去
    text = text.replace(",", "").replace("+", "").strip()
    return text


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------
def safe_int(value: str, *, default: Optional[int] = 0) -> Optional[int]:
    """差枚・回転数などの文字列を int に変換する.

    - 全角数字を半角に正規化
    - 各種マイナス記号 (−, –, ー, ＝) を統一処理
    - カンマ・プラス記号を除去
    - 空文字・ハイフン単体は *default* を返す

    Args:
        value: 変換対象の文字列 (例: "+2,150", "-500", "8,432", "", "-")
        default: 変換不能時に返す値 (デフォルト 0, None も可)

    Returns:
        int または default
    """
    cleaned = _normalize(value)
    if not cleaned or cleaned == "-":
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def safe_float(value: str, *, default: Optional[float] = 0.0) -> Optional[float]:
    """出率・勝率などのパーセント文字列を float に変換する.

    - "112.3%" → 112.3
    - "80%" → 80.0
    - 空文字 → default

    Args:
        value: 変換対象の文字列 (例: "112.3%", "80%", "")
        default: 変換不能時に返す値

    Returns:
        float または default
    """
    cleaned = _normalize(value)
    # パーセント記号を除去
    cleaned = _PERCENT_RE.sub("", cleaned)
    if not cleaned or cleaned == "-":
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def strip_rating_symbol(text: str) -> str:
    """機種名から評価記号 (☆◎◯▲△○) を除去する.

    みんレポでは機種名の先頭に ☆/◎/◯/▲ が付くことがある。

    Args:
        text: 機種名文字列 (例: "◎ マイジャグラーV")

    Returns:
        記号除去後の文字列 (例: "マイジャグラーV")
    """
    return re.sub(r"^[☆◎◯○▲△\s]+", "", text).strip()
