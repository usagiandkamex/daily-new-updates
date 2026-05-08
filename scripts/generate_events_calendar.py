"""connpass イベントカレンダーデータ生成スクリプト

関東（東京都・神奈川県）またはオンラインで開催される IT 系イベントを
connpass から取得し、docs/events.json に保存する。

Usage:
    python scripts/generate_events_calendar.py
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import feedparser
import requests

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

CONNPASS_RSS_URL = "https://connpass.com/search/"

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; daily-new-updates-bot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

JST = timezone(timedelta(hours=9), "JST")

# 関東の都道府県 ID（connpass search の pref_id パラメータ）
_PREFECTURE_IDS: dict[str, int] = {
    "東京都": 13,
    "神奈川県": 14,
}

# 当月 + 何か月先まで取得するか
CALENDAR_LOOKAHEAD_MONTHS = 2

# 保存する最大イベント件数
MAX_CALENDAR_EVENTS = 500

# イベント説明を取得するイベントの最大件数
MAX_ENRICH_EVENTS = 100

# 説明文の最大文字数（これを超えたら切り詰め）
MAX_DESCRIPTION_CHARS = 400

# 説明取得の並列数
_ENRICH_WORKERS = 5

# イベントページ取得タイムアウト（秒）
_PAGE_FETCH_TIMEOUT = 10

# ---------------------------------------------------------------------------
# IT 関連イベント判定
# ---------------------------------------------------------------------------

_IT_KEYWORDS: list[str] = [
    # クラウド・インフラ
    "cloud", "クラウド", "azure", "aws", "gcp", "google cloud",
    "kubernetes", "k8s", "docker", "terraform", "ansible", "iac",
    "serverless", "サーバーレス", "container", "コンテナ",
    # DevOps・SRE・運用
    "devops", "devsecops", "mlops", "aiops", "finops",
    "platform engineering",
    # AI・機械学習
    "llm", "機械学習", "深層学習", "deep learning",
    "chatgpt", "openai", "anthropic", "copilot", "生成ai", "生成AI",
    "langchain", "hugging face",
    # セキュリティ
    "security", "セキュリティ", "脆弱性", "pentest",
    "zerotrust", "zero trust", "ゼロトラスト",
    # プログラミング言語・フレームワーク
    "python", "javascript", "typescript", "java", "rust",
    "react", "vue", "angular", "django", "rails",
    "マイクロサービス", "microservices",
    # データ・分析
    "データ", "analytics", "アナリティクス", "databricks", "snowflake", "bigquery",
    # IT全般
    "エンジニア", "engineer", "developer", "デベロッパー",
    "プログラミング", "programming", "iot", "5g",
    # コミュニティ・イベント形式
    "勉強会", "ハンズオン", "オープンソース", "open source",
    # コミュニティ名
    "jaws", "jawsug", "azure user group", "jug", "gcpug",
    "microsoft",
    # IT インフラ・その他
    "インフラ", "infra", "database", "blockchain", "web3",
]

_IT_KEYWORDS_WORD_BOUNDARY: frozenset[str] = frozenset({
    "ai", "ml", "go", "sre", "rag", "soc", "db", "api",
})


def _is_it_event(title: str, desc: str) -> bool:
    """イベントが IT 関連かどうかを判定する。"""
    text = (title + " " + desc).lower()
    for kw in _IT_KEYWORDS:
        if kw.lower() in text:
            return True
    for kw in _IT_KEYWORDS_WORD_BOUNDARY:
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text):
            return True
    return False


# ---------------------------------------------------------------------------
# connpass イベントページから説明文を取得
# ---------------------------------------------------------------------------

class _ConnpassEventPageParser(HTMLParser):
    """connpass イベントページから説明文（event_description_content）を抽出する。"""

    _TARGET_CLASS = "event_description_content"

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_target = False
        self._target_tag = ""
        self._depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if not self._in_target:
            attr_dict = dict(attrs)
            classes = set((attr_dict.get("class") or "").split())
            if self._TARGET_CLASS in classes:
                self._in_target = True
                self._target_tag = tag
                self._depth = 0
        elif tag == self._target_tag:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._in_target:
            return
        if tag == self._target_tag:
            if self._depth == 0:
                self._in_target = False
            else:
                self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_target:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(part for part in self._parts if part.strip())


_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; daily-new-updates-bot/1.0)",
    "Accept": "text/html",
}


def _fetch_event_description(url: str) -> str:
    """connpass イベントページから説明文テキストを取得して返す。

    取得に失敗した場合は空文字列を返す。
    """
    try:
        resp = requests.get(url, headers=_PAGE_HEADERS, timeout=_PAGE_FETCH_TIMEOUT)
        resp.raise_for_status()
        parser = _ConnpassEventPageParser()
        parser.feed(resp.text)
        # 余分な空白を正規化して返す
        return " ".join(parser.get_text().split())
    except requests.RequestException as exc:
        print(f"  connpass: 説明文取得失敗 ({url}): {type(exc).__name__}")
        return ""
    except Exception as exc:
        print(f"  connpass: 説明文取得で予期しないエラー ({url}): {type(exc).__name__}")
        return ""


def _enrich_descriptions(events: list[dict]) -> None:
    """connpass イベントページからイベント説明を取得し description フィールドを追加する。

    対象は HTTPS URL を持つ先頭 MAX_ENRICH_EVENTS 件のみ。取得したテキストは
    MAX_DESCRIPTION_CHARS 文字に切り詰めて保存する。
    """
    targets = [ev for ev in events if ev.get("event_url", "").startswith("https://")]
    targets = targets[:MAX_ENRICH_EVENTS]
    if not targets:
        return

    print(f"  イベント説明を取得中 ({len(targets)} 件)…")

    def _fetch_one(ev: dict) -> tuple[dict, str]:
        return ev, _fetch_event_description(ev["event_url"])

    done = 0
    with ThreadPoolExecutor(max_workers=_ENRICH_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, ev): ev for ev in targets}
        for future in as_completed(futures):
            try:
                ev, text = future.result()
                if text:
                    if len(text) > MAX_DESCRIPTION_CHARS:
                        # 単語境界で切り詰め
                        text = text[:MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
                    ev["description"] = text
            except Exception as exc:
                print(f"  connpass: 説明文補完で予期しないエラー: {type(exc).__name__}")
            done += 1
            if done % 20 == 0:
                print(f"    {done}/{len(targets)} 件完了")

    print(f"  説明文取得完了（{sum(1 for ev in targets if ev.get('description'))} 件取得）")


# ---------------------------------------------------------------------------
# RSS パース
# ---------------------------------------------------------------------------

def _parse_started_at(entry) -> str:
    """feedparser エントリから開催日時文字列（JST）を取得する。"""
    pub = entry.get("published_parsed")
    if pub is None:
        return ""
    try:
        dt = datetime(*pub[:6], tzinfo=timezone.utc).astimezone(JST)
        return dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# イベント取得
# ---------------------------------------------------------------------------

def _build_search_months(today: datetime, lookahead: int) -> list[str]:
    """当月から lookahead か月先までの YYYYMM リストを返す。"""
    months: list[str] = []
    y, m = today.year, today.month
    for _ in range(lookahead + 1):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def fetch_events(today: datetime) -> list[dict]:
    """今日以降のイベントを connpass RSS から取得する。

    関東（東京都・神奈川県）の pref_id 検索とオンライン（online=1）検索の
    2 系統で取得し、重複を排除して日時昇順に返す。
    """
    today_str = today.strftime("%Y/%m/%d")
    months = _build_search_months(today, CALENDAR_LOOKAHEAD_MONTHS)

    events: list[dict] = []
    seen_urls: set[str] = set()

    # --- 都道府県別検索 ---
    for pref, pref_id in _PREFECTURE_IDS.items():
        for ym in months:
            params = {"format": "rss", "pref_id": pref_id, "ym": ym}
            try:
                resp = requests.get(
                    CONNPASS_RSS_URL,
                    params=params,
                    headers=HTTP_HEADERS,
                    timeout=15,
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
                count = 0
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url or url in seen_urls:
                        continue
                    title = entry.get("title", "").strip()
                    desc = entry.get("summary", "").strip()
                    if not _is_it_event(title, desc):
                        continue
                    started_at = _parse_started_at(entry)
                    # 過去イベントをスキップ（日時不明は残す）
                    if started_at and started_at[:10] < today_str:
                        continue
                    seen_urls.add(url)
                    events.append({
                        "title": title,
                        "event_url": url,
                        "started_at": started_at,
                        "place": "",
                        "catch": desc[:200],
                    })
                    count += 1
                print(f"  connpass RSS ({pref} {ym}): {count} 件取得")
            except Exception as e:
                print(f"  connpass RSS ({pref} {ym}): 取得失敗 ({e})")

    # --- オンラインイベント検索 ---
    for ym in months:
        params = {"format": "rss", "online": 1, "ym": ym}
        try:
            resp = requests.get(
                CONNPASS_RSS_URL,
                params=params,
                headers=HTTP_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            count = 0
            for entry in feed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue
                title = entry.get("title", "").strip()
                desc = entry.get("summary", "").strip()
                if not _is_it_event(title, desc):
                    continue
                started_at = _parse_started_at(entry)
                if started_at and started_at[:10] < today_str:
                    continue
                seen_urls.add(url)
                events.append({
                    "title": title,
                    "event_url": url,
                    "started_at": started_at,
                    "place": "オンライン",
                    "catch": desc[:200],
                })
                count += 1
            print(f"  connpass RSS (オンライン {ym}): {count} 件取得")
        except Exception as e:
            print(f"  connpass RSS (オンライン {ym}): 取得失敗 ({e})")

    # 日時昇順ソート（日時不明は末尾）
    events.sort(
        key=lambda e: (0, e["started_at"]) if e.get("started_at") else (1, "")
    )

    if len(events) > MAX_CALENDAR_EVENTS:
        print(f"  ※ {len(events)} 件 → {MAX_CALENDAR_EVENTS} 件に制限")
        events = events[:MAX_CALENDAR_EVENTS]

    # connpass イベントページからイベント説明を取得
    _enrich_descriptions(events)

    return events


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    today = datetime.now(JST)
    print(f"イベントカレンダーデータ生成開始: {today.strftime('%Y-%m-%d %H:%M JST')}")

    events = fetch_events(today)
    print(f"取得イベント数: {len(events)}")

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": events,
    }

    docs_dir = Path(__file__).parent.parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    out = docs_dir / "events.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"保存完了: {out} ({len(events)} イベント)")


if __name__ == "__main__":
    main()
