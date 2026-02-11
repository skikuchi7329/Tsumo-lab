"""min-repo.com (みんレポ) 2段階スクレイパー.

Stage 1: タグページからレポート URL + 日付を取得 (fetch_report_urls)
Stage 2: 各レポートページから台別データ + 機種別集計を抽出
         (parse_report_page / parse_machine_stats)

URL 構造:
  店舗トップ: https://min-repo.com/tag/麗都荒川沖/  (日本語→自動URLエンコード)
  個別レポート: https://min-repo.com/{id}/  (数値ID、自動取得)

NOTE: CSS セレクタは定数 (SELECTORS) にまとめているので、
      サイト構造が変わった場合はここだけ修正すれば OK。
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, Tag

from models.schema import MachineStats, SlotData
from utils.parser_helper import safe_float, safe_int, strip_rating_symbol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS セレクタ / 正規表現 — サイト構造変更時はここを修正
# ---------------------------------------------------------------------------

# タグページ (レポート一覧) 用
SELECTORS = {
    # 各レポート記事を包む要素
    "article": "article",
    # 記事タイトル内のリンク (href = レポート URL)
    "title_link": "h2 a, h3 a, .entry-title a",
    # レポートページ内: 機種ブロック (機種名 + テーブル)
    "machine_section": "table",
    # 機種名が入る見出し (テーブルの直前の h2/h3/h4 またはキャプション)
    "machine_heading": "h2, h3, h4, caption, .machine-name",
    # データ行
    "data_row": "tr",
}

# タイトルから日付を抽出する正規表現
# "2025/6/7(土) レイト荒川沖" / "1/27(火) レイト荒川沖"
DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})?/?(?P<month>\d{1,2})/(?P<day>\d{1,2})"
)


# ---------------------------------------------------------------------------
# データ型
# ---------------------------------------------------------------------------
@dataclass
class ReportLink:
    """タグページから取得した 1 件のレポートリンク."""
    url: str
    date: datetime
    title: str


# タイトルから日付 + 曜日部分を除去して店舗名部分だけを残す正規表現
_TITLE_DATE_PREFIX = re.compile(
    r"^(?:\d{4})?/?(?:\d{1,2})/(?:\d{1,2})\s*(?:\([^)]*\))?\s*"
)


def _extract_shop_part(title: str) -> str:
    """タイトルから日付部分を除去して店舗名部分を返す.

    例: "2/10(火)" → ""  (日付のみ = 対象店舗)
        "2/7(土) 京都駅前ラッキー" → "京都駅前ラッキー"
    """
    return _TITLE_DATE_PREFIX.sub("", title).strip()


def filter_links_by_shop(
    links: list[ReportLink],
    title_keywords: list[str] | None = None,
) -> list[ReportLink]:
    """レポートリンクを店舗名でフィルタリングする.

    対象とするレポート:
      1. タイトルが「日付のみ」(店舗名部分が空) → タグ対象店舗のレポート
      2. タイトルに title_keywords のいずれかが含まれる

    Args:
        links: フィルタ前のレポートリンク一覧
        title_keywords: 対象店舗のキーワードリスト (例: ["麗都荒川沖", "レイト荒川沖"])

    Returns:
        フィルタ後のリスト
    """
    if not title_keywords:
        return links

    filtered: list[ReportLink] = []
    for link in links:
        shop_part = _extract_shop_part(link.title)
        if not shop_part:
            # 日付のみ = タグ対象店舗
            filtered.append(link)
        elif any(kw in link.title for kw in title_keywords):
            filtered.append(link)
        else:
            logger.debug("  [FILTER] Skipped (other shop): %s", link.title)
    return filtered


# ---------------------------------------------------------------------------
# HTTP セッション — ブラウザに近いヘッダでボット判定を回避
# ---------------------------------------------------------------------------
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# スリープ間隔 (秒) — リクエスト間にランダムな待機を入れる
SLEEP_MIN = 3.0
SLEEP_MAX = 5.0


def _create_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent or DEFAULT_UA,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://min-repo.com/",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    })
    return session


def _random_sleep() -> None:
    """リクエスト間に 3〜5 秒のランダムな待機を入れる."""
    delay = random.uniform(SLEEP_MIN, SLEEP_MAX)
    logger.debug("Sleeping %.1f seconds", delay)
    time.sleep(delay)


# ---------------------------------------------------------------------------
# Stage 1: タグページ → レポート URL 一覧
# ---------------------------------------------------------------------------
def _parse_date_from_title(title: str, fallback_year: int | None = None) -> Optional[datetime]:
    """タイトル文字列から日付を抽出する.

    Args:
        title: 記事タイトル (例: "2025/6/7(土) レイト荒川沖")
        fallback_year: 年が省略されている場合に使う年

    Returns:
        datetime or None
    """
    m = DATE_PATTERN.search(title)
    if not m:
        return None
    year = int(m.group("year")) if m.group("year") else fallback_year
    if year is None:
        year = datetime.now().year
    month = int(m.group("month"))
    day = int(m.group("day"))
    try:
        return datetime(year, month, day)
    except ValueError:
        logger.warning("Invalid date in title: %s", title)
        return None


def fetch_report_urls_from_html(html: str, base_url: str = "https://min-repo.com") -> list[ReportLink]:
    """タグページの HTML をパースしてレポートリンク一覧を返す.

    HTML を引数で受け取るため、テスト時にネットワーク不要。
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[ReportLink] = []

    # article 要素を探す
    articles = soup.select(SELECTORS["article"])

    if articles:
        for article in articles:
            link_tag = article.select_one(SELECTORS["title_link"])
            if not link_tag or not link_tag.get("href"):
                continue
            url = link_tag["href"]
            title = link_tag.get_text(strip=True)
            dt = _parse_date_from_title(title)
            if dt is None:
                logger.debug("Date not found in title: %s", title)
                continue
            results.append(ReportLink(url=url, date=dt, title=title))
    else:
        # article 要素がない場合はページ全体からリンクを探す
        for a_tag in soup.select("a[href]"):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)
            # レポートURLは数値IDのパスを持つ: /123456/
            if re.search(r"/\d{4,}/", href) and DATE_PATTERN.search(text):
                dt = _parse_date_from_title(text)
                if dt:
                    results.append(ReportLink(url=href, date=dt, title=text))

    # 日付の新しい順にソート
    results.sort(key=lambda r: r.date, reverse=True)
    return results


def _encode_shop_name(shop_name: str) -> str:
    """店舗名を URL パスに使える形にエンコードする.

    既にエンコード済み (%XX 形式) の場合はそのまま返す。
    日本語文字列の場合は urllib.parse.quote でエンコードする。

    例: "麗都荒川沖" → "%E9%BA%97%E9%83%BD%E8%8D%92%E5%B7%9D%E6%B2%96"
    """
    if "%" in shop_name:
        # 既にエンコード済みと判断
        return shop_name
    return quote(shop_name, safe="")


def fetch_report_urls(
    shop_name: str,
    base_url: str = "https://min-repo.com",
    user_agent: str = DEFAULT_UA,
    days: int | None = None,
    max_pages: int = 10,
) -> list[ReportLink]:
    """タグページにアクセスしてレポート URL 一覧を返す (ネットワーク版).

    店舗名（日本語）を指定するだけで、URL エンコードを自動で行う。
    days を指定すると、最新の日付から days 日分のレポートのみ返す。
    ページネーションも自動で行い、必要な日数分のデータが揃うまでページを辿る。

    Args:
        shop_name: 店舗名 (日本語 or URL エンコード済み、どちらでも可)
        base_url: サイトのベース URL
        user_agent: リクエストに使う User-Agent
        days: 取得する日数 (None なら全件)
        max_pages: 最大ページ数 (安全上限)

    Returns:
        日付降順のレポートリンクリスト
    """
    encoded_name = _encode_shop_name(shop_name)
    session = _create_session(user_agent)
    all_links: list[ReportLink] = []

    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"{base_url}/tag/{encoded_name}/"
        else:
            url = f"{base_url}/tag/{encoded_name}/page/{page}/"

        if page > 1:
            _random_sleep()

        logger.info("Fetching tag page: %s (page %d)", url, page)
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 404:
                # ページネーション終端
                logger.info("Page %d returned 404, stopping pagination", page)
                break
            raise

        links = fetch_report_urls_from_html(resp.text, base_url)
        if not links:
            logger.info("No links found on page %d, stopping pagination", page)
            break
        all_links.extend(links)

        # days 指定がある場合: 十分な日数分取れたか判定
        if days is not None and all_links:
            all_links_sorted = sorted(all_links, key=lambda r: r.date, reverse=True)
            newest = all_links_sorted[0].date
            oldest = all_links_sorted[-1].date
            if (newest - oldest).days >= days:
                logger.info(
                    "Collected %d days of data (target: %d), stopping pagination",
                    (newest - oldest).days, days,
                )
                break

    # 重複排除 (URL ベース)
    seen: set[str] = set()
    unique: list[ReportLink] = []
    for link in all_links:
        if link.url not in seen:
            seen.add(link.url)
            unique.append(link)

    unique.sort(key=lambda r: r.date, reverse=True)

    # days 指定がある場合: 最新日付から days 日以内のみに絞り込む
    if days is not None and unique:
        newest_date = unique[0].date
        cutoff = newest_date - timedelta(days=days)
        unique = [link for link in unique if link.date >= cutoff]
        logger.info(
            "Filtered to %d links within %d days (since %s)",
            len(unique), days, cutoff.strftime("%Y-%m-%d"),
        )

    return unique


# ---------------------------------------------------------------------------
# Stage 2: レポートページ → 台別データ + 機種別集計
# ---------------------------------------------------------------------------

# _safe_int は後方互換性のためラッパーとして残す (既存テストが参照)
def _safe_int(value: str) -> int:
    """カンマ・符号付き文字列を int に変換する. 変換不能なら 0."""
    result = safe_int(value, default=0)
    return result if result is not None else 0


def _find_machine_name_before_table(table: Tag) -> str:
    """テーブル直前の見出し要素から機種名を探す."""
    # caption があればそれを使う
    caption = table.find("caption")
    if caption:
        return caption.get_text(strip=True)

    # テーブル直前の兄弟要素を遡って見出しを探す
    prev = table.find_previous_sibling()
    while prev:
        if prev.name in ("h2", "h3", "h4", "h5"):
            return prev.get_text(strip=True)
        # 見出し以外の要素 (div, p) にも機種名が入る場合
        if prev.name in ("div", "p") and prev.get("class"):
            text = prev.get_text(strip=True)
            if text and len(text) < 50:
                return text
        prev = prev.find_previous_sibling()

    # find_previous (兄弟以外も含む)
    heading = table.find_previous(["h2", "h3", "h4"])
    if heading:
        return heading.get_text(strip=True)

    return "不明"


def _detect_columns(header_row: Tag) -> dict[str, int] | None:
    """テーブルのヘッダ行からカラムインデックスを推定する.

    台別データ用。

    Returns:
        {"unit": idx, "g_count": idx, "diff": idx, "bb": idx, "rb": idx}
        推定不能なら None
    """
    cells = header_row.find_all(["th", "td"])
    texts = [c.get_text(strip=True) for c in cells]

    mapping: dict[str, int] = {}
    for i, t in enumerate(texts):
        tl = t.lower()
        if "台番" in t or "番号" in t or t == "台":
            mapping["unit"] = i
        elif "Ｇ" in t or "g数" in tl or "回転" in t or "ゲーム" in t or tl == "g":
            mapping["g_count"] = i
        elif "差枚" in t or "差玉" in t or "出玉" in t:
            mapping["diff"] = i
        elif tl == "bb" or "BB" in t or "BIG" in t.upper():
            mapping["bb"] = i
        elif tl == "rb" or "RB" in t or "REG" in t.upper():
            mapping["rb"] = i

    # 最低限 unit が特定できればデータを取得する
    if "unit" not in mapping:
        return None
    return mapping


def _detect_summary_columns(header_row: Tag) -> dict[str, int] | None:
    """機種別サマリーテーブルのヘッダ行からカラムインデックスを推定する.

    みんレポの機種別集計テーブルには以下のカラムが含まれる:
        機種, (台数,) 平均差枚, 平均G数, 勝率, 出率

    Returns:
        {"machine": idx, "unit_count": idx, "avg_diff": idx,
         "avg_g": idx, "win_rate": idx, "payout_rate": idx}
        サマリーテーブルでなければ None
    """
    cells = header_row.find_all(["th", "td"])
    texts = [c.get_text(strip=True) for c in cells]

    mapping: dict[str, int] = {}
    for i, t in enumerate(texts):
        if "機種" in t or t == "機種名":
            mapping["machine"] = i
        elif "台数" in t:
            mapping["unit_count"] = i
        elif "平均差枚" in t or "平均差玉" in t:
            mapping["avg_diff"] = i
        elif "平均G数" in t or "平均g数" in t.lower() or "平均ゲーム" in t or "平均回転" in t:
            mapping["avg_g"] = i
        elif "勝率" in t:
            mapping["win_rate"] = i
        elif "出率" in t or "出玉率" in t:
            mapping["payout_rate"] = i

    # 「機種」カラムが必須。加えて avg_diff/win_rate/payout_rate のいずれかがあればサマリー
    if "machine" not in mapping:
        return None
    has_stats = any(k in mapping for k in ("avg_diff", "win_rate", "payout_rate"))
    if not has_stats:
        return None
    return mapping


def parse_report_page_from_html(
    html: str,
    report_date: datetime,
    shop_id: str,
) -> list[SlotData]:
    """レポートページの HTML をパースして台別データを返す.

    HTML を引数で受け取るため、テスト時にネットワーク不要。
    """
    soup = BeautifulSoup(html, "lxml")
    records: list[SlotData] = []

    tables = soup.select(SELECTORS["machine_section"])

    for table in tables:
        rows = table.select(SELECTORS["data_row"])
        if not rows:
            continue

        # 1行目をヘッダとして列位置を検出
        col_map = _detect_columns(rows[0])
        if col_map is None:
            # サマリーテーブルかもしれないのでスキップ (parse_machine_stats で処理)
            continue

        machine_name = _find_machine_name_before_table(table)

        # データ行をパース
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(col_map.values()):
                continue

            unit_text = cells[col_map["unit"]].get_text(strip=True)
            unit_number = _safe_int(unit_text)
            if unit_number == 0:
                continue  # 台番号が取れない行はスキップ

            g_count = _safe_int(cells[col_map["g_count"]].get_text(strip=True)) if "g_count" in col_map else 0
            diff_payout = _safe_int(cells[col_map["diff"]].get_text(strip=True)) if "diff" in col_map else 0
            bb_count = _safe_int(cells[col_map["bb"]].get_text(strip=True)) if "bb" in col_map else 0
            rb_count = _safe_int(cells[col_map["rb"]].get_text(strip=True)) if "rb" in col_map else 0

            records.append(SlotData(
                date=report_date,
                shop_id=shop_id,
                machine_name=machine_name,
                unit_number=unit_number,
                g_count=g_count,
                diff_payout=diff_payout,
                bb_count=bb_count,
                rb_count=rb_count,
            ))

    logger.info("Parsed %d slot records from report page", len(records))
    return records


def parse_machine_stats_from_html(
    html: str,
    report_date: datetime,
    shop_id: str,
) -> list[MachineStats]:
    """レポートページの HTML をパースして機種別集計データを返す.

    みんレポのレポートページには機種別サマリーテーブルが含まれ、
    各機種の平均差枚・平均G数・勝率・出率が記載されている。

    Args:
        html: レポートページの HTML 文字列
        report_date: レポートの営業日
        shop_id: 店舗ID

    Returns:
        MachineStats のリスト
    """
    soup = BeautifulSoup(html, "lxml")
    stats: list[MachineStats] = []

    tables = soup.select(SELECTORS["machine_section"])

    for table in tables:
        rows = table.select(SELECTORS["data_row"])
        if not rows:
            continue

        col_map = _detect_summary_columns(rows[0])
        if col_map is None:
            continue  # サマリーテーブルではない

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(col_map.values()):
                continue

            raw_name = cells[col_map["machine"]].get_text(strip=True)
            if not raw_name:
                continue
            machine_name = strip_rating_symbol(raw_name)

            unit_count = _safe_int(
                cells[col_map["unit_count"]].get_text(strip=True)
            ) if "unit_count" in col_map else 0

            avg_diff = _safe_int(
                cells[col_map["avg_diff"]].get_text(strip=True)
            ) if "avg_diff" in col_map else 0

            avg_g_text = (
                cells[col_map["avg_g"]].get_text(strip=True)
                if "avg_g" in col_map else "0"
            )
            avg_g = _safe_int(avg_g_text)

            win_rate_text = (
                cells[col_map["win_rate"]].get_text(strip=True)
                if "win_rate" in col_map else "0"
            )
            win_rate = safe_float(win_rate_text, default=0.0) or 0.0

            payout_rate_text = (
                cells[col_map["payout_rate"]].get_text(strip=True)
                if "payout_rate" in col_map else "0"
            )
            payout_rate = safe_float(payout_rate_text, default=0.0) or 0.0

            stats.append(MachineStats(
                date=report_date,
                shop_id=shop_id,
                machine_name=machine_name,
                unit_count=unit_count,
                avg_diff_payout=avg_diff,
                avg_g_count=avg_g,
                win_rate=win_rate,
                payout_rate=payout_rate,
            ))

    logger.info("Parsed %d machine stats from report page", len(stats))
    return stats


def parse_report_page(
    report_url: str,
    report_date: datetime,
    shop_id: str,
    user_agent: str = DEFAULT_UA,
) -> list[SlotData]:
    """レポートページにアクセスして台別データを返す (ネットワーク版)."""
    session = _create_session(user_agent)
    logger.info("Fetching report page: %s", report_url)
    resp = session.get(report_url, timeout=30)
    resp.raise_for_status()
    return parse_report_page_from_html(resp.text, report_date, shop_id)


def parse_machine_stats(
    report_url: str,
    report_date: datetime,
    shop_id: str,
    user_agent: str = DEFAULT_UA,
) -> list[MachineStats]:
    """レポートページにアクセスして機種別集計データを返す (ネットワーク版)."""
    session = _create_session(user_agent)
    logger.info("Fetching report page for stats: %s", report_url)
    resp = session.get(report_url, timeout=30)
    resp.raise_for_status()
    return parse_machine_stats_from_html(resp.text, report_date, shop_id)


def fetch_and_parse_report(
    report_url: str,
    report_date: datetime,
    shop_id: str,
    user_agent: str = DEFAULT_UA,
) -> tuple[list[SlotData], list[MachineStats]]:
    """レポートページから台別データ + 機種別集計を一括取得する.

    1回のHTTPリクエストで両方のデータを抽出する。

    Returns:
        (slot_records, machine_stats) のタプル
    """
    session = _create_session(user_agent)
    logger.info("Fetching report page: %s", report_url)
    resp = session.get(report_url, timeout=30)
    resp.raise_for_status()
    html = resp.text

    slot_records = parse_report_page_from_html(html, report_date, shop_id)
    machine_stats = parse_machine_stats_from_html(html, report_date, shop_id)
    return slot_records, machine_stats
