"""min-repo.com (みんレポ) 2段階スクレイパー.

Stage 1: タグページからレポート URL + 日付を取得 (fetch_report_urls)
Stage 2: 各レポートページから台別データを抽出 (parse_report_page)

NOTE: CSS セレクタは定数 (SELECTORS) にまとめているので、
      サイト構造が変わった場合はここだけ修正すれば OK。
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

from models.schema import SlotData

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


def fetch_report_urls(
    tag_name: str,
    base_url: str = "https://min-repo.com",
    user_agent: str = DEFAULT_UA,
    max_pages: int = 1,
) -> list[ReportLink]:
    """タグページにアクセスしてレポート URL 一覧を返す (ネットワーク版).

    Args:
        tag_name: URL エンコード済みの店舗タグ名
        base_url: サイトのベース URL
        user_agent: リクエストに使う User-Agent
        max_pages: 取得するページ数 (ページネーション対応)

    Returns:
        日付降順のレポートリンクリスト
    """
    session = _create_session(user_agent)
    all_links: list[ReportLink] = []

    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"{base_url}/tag/{tag_name}/"
        else:
            url = f"{base_url}/tag/{tag_name}/page/{page}/"

        if page > 1:
            _random_sleep()

        logger.info("Fetching tag page: %s", url)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        links = fetch_report_urls_from_html(resp.text, base_url)
        if not links:
            break
        all_links.extend(links)

    # 重複排除 (URL ベース)
    seen: set[str] = set()
    unique: list[ReportLink] = []
    for link in all_links:
        if link.url not in seen:
            seen.add(link.url)
            unique.append(link)

    unique.sort(key=lambda r: r.date, reverse=True)
    return unique


# ---------------------------------------------------------------------------
# Stage 2: レポートページ → 台別データ
# ---------------------------------------------------------------------------
def _safe_int(value: str) -> int:
    """カンマ・符号付き文字列を int に変換する. 変換不能なら 0."""
    cleaned = value.replace(",", "").replace("+", "").strip()
    if not cleaned or cleaned == "-":
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


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
        machine_name = _find_machine_name_before_table(table)

        rows = table.select(SELECTORS["data_row"])
        if not rows:
            continue

        # 1行目をヘッダとして列位置を検出
        col_map = _detect_columns(rows[0])
        if col_map is None:
            # ヘッダが見つからなければテーブルをスキップ
            logger.debug("Column mapping not found for table under: %s", machine_name)
            continue

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

    logger.info("Parsed %d records from report page", len(records))
    return records


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
