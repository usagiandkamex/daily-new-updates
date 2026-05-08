"""connpass イベントカレンダーデータ生成スクリプト

関東（東京都・神奈川県）またはオンラインで開催される IT 系イベントを
connpass から取得し、docs/events.json に保存する。

Usage:
    python scripts/generate_events_calendar.py
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

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

# 大手ベンダー・大規模カンファレンス情報取得用 RSS フィード（Google News 検索）
# 各フィードには「name」（表示名）「url」（RSS URL）「place」（開催場所候補）を定義する。
VENDOR_EVENT_NEWS_FEEDS: list[dict] = [
    # Microsoft
    {
        "name": "Microsoft Build",
        "url": "https://news.google.com/rss/search?q=Microsoft+Build+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E6%83%85%E5%A0%B1&hl=ja&gl=JP&ceid=JP:ja",
        "place": "Seattle / オンライン",
    },
    {
        "name": "Microsoft Ignite",
        "url": "https://news.google.com/rss/search?q=Microsoft+Ignite+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "Chicago / オンライン",
    },
    # AWS
    {
        "name": "AWS Summit Japan",
        "url": "https://news.google.com/rss/search?q=AWS+Summit+Japan+%E9%96%8B%E5%82%AC+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&hl=ja&gl=JP&ceid=JP:ja",
        "place": "東京 / オンライン",
    },
    {
        "name": "AWS re:Invent",
        "url": "https://news.google.com/rss/search?q=AWS+re%3AInvent+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "Las Vegas / オンライン",
    },
    # Google Cloud
    {
        "name": "Google Cloud Next",
        "url": "https://news.google.com/rss/search?q=Google+Cloud+Next+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E6%83%85%E5%A0%B1&hl=ja&gl=JP&ceid=JP:ja",
        "place": "Las Vegas / オンライン",
    },
    # CNCF・大規模コミュニティカンファレンス
    {
        "name": "KubeCon + CloudNativeCon",
        "url": "https://news.google.com/rss/search?q=KubeCon+CloudNativeCon+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "現地開催 / オンライン",
    },
    # Linux Foundation
    {
        "name": "Open Source Summit Japan",
        "url": "https://news.google.com/rss/search?q=Open+Source+Summit+Japan+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "東京 / オンライン",
    },
    # HashiCorp
    {
        "name": "HashiConf",
        "url": "https://news.google.com/rss/search?q=HashiConf+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "現地開催 / オンライン",
    },
    # GitHub
    {
        "name": "GitHub Universe",
        "url": "https://news.google.com/rss/search?q=GitHub+Universe+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E6%83%85%E5%A0%B1&hl=ja&gl=JP&ceid=JP:ja",
        "place": "San Francisco / オンライン",
    },
    # Red Hat
    {
        "name": "Red Hat Summit",
        "url": "https://news.google.com/rss/search?q=Red+Hat+Summit+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "Boston / オンライン",
    },
    # VMware (Broadcom)
    {
        "name": "VMware Explore",
        "url": "https://news.google.com/rss/search?q=VMware+Explore+%E3%82%AB%E3%83%B3%E3%83%95%E3%82%A1%E3%83%AC%E3%83%B3%E3%82%B9+%E5%A0%B1%E5%91%8A&hl=ja&gl=JP&ceid=JP:ja",
        "place": "Las Vegas / オンライン",
    },
]

# ベンダーイベントニュース：フィードごとの最大取得記事数
_VENDOR_EVENT_MAX_ENTRIES_PER_FEED = 5

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


def _is_connpass_event_url(url: str) -> bool:
    """URL が connpass.com（サブドメイン可）の HTTPS イベント URL かを判定する。

    SSRF 対策として、`_enrich_descriptions()` の HTTP 取得対象を connpass.com に
    限定するために使用する。
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host != "connpass.com" and not host.endswith(".connpass.com"):
        return False
    # 説明文取得対象は connpass の「イベントページ」(/event/...) のみに限定する。
    return parsed.path.startswith("/event/")


def _truncate_description(text: str, max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    """説明文を max_chars 文字以内に切り詰める（"…" を含めて max_chars 以内）。

    超過時は単語境界（最後のスペース）で切り詰めて末尾に "…" を付与する。
    """
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"[:max_chars]
    # "…" 1 文字分を確保した上で単語境界を探す。
    head = text[: max_chars - 1]
    boundary = head.rsplit(" ", 1)[0] if " " in head else head
    return boundary + "…"


def _fetch_event_description(url: str) -> str:
    """connpass イベントページから説明文テキストを取得して返す。

    取得に失敗した場合は空文字列を返す。
    """
    try:
        resp = requests.get(
            url,
            headers=_PAGE_HEADERS,
            timeout=_PAGE_FETCH_TIMEOUT,
            allow_redirects=False,
        )
        # SSRF 対策: リダイレクトに追従しない。3xx は connpass 外への遷移
        # 可能性があるため失敗扱いとする（allow_redirects=False のため
        # requests は 3xx をそのまま返す）。
        if 300 <= resp.status_code < 400:
            print(
                f"  connpass: 説明文取得スキップ (リダイレクト {resp.status_code}): {url}"
            )
            return ""
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

    対象は connpass.com の HTTPS URL を持つ先頭 MAX_ENRICH_EVENTS 件のみ
    （SSRF 対策で他ホストは除外）。取得したテキストは MAX_DESCRIPTION_CHARS
    文字に切り詰めて保存する。
    """
    targets = [ev for ev in events if _is_connpass_event_url(ev.get("event_url", ""))]
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
                    ev["description"] = _truncate_description(text)
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


def _fetch_rss_events(
    params: dict,
    place: str,
    today_str: str,
    seen_urls: set[str],
    label: str,
) -> tuple[list[dict], bool]:
    """connpass RSS を1回呼び出してイベントリストを返す（共通処理）。

    - URL 重複（seen_urls）と IT キーワードフィルタを適用
    - 開催日が today_str より前のイベントは除外（日付単位、当日は表示対象）
    - 取得件数はログに出力
    - 戻り値は (収集したイベント, 成功フラグ)。HTTP 例外、または
      ``feedparser`` がパース失敗（``feed.bozo`` が真かつ ``entries`` が空）
      とした場合は成功フラグ False を返す。
    """
    collected: list[dict] = []
    try:
        resp = requests.get(
            CONNPASS_RSS_URL,
            params=params,
            headers=HTTP_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        # feedparser はパース失敗を例外ではなく feed.bozo フラグで通知する。
        # 壊れた RSS / 想定外レスポンス（HTML エラーページ等）を成功扱いに
        # してしまうと events.json を空で上書きする恐れがあるため、
        # entries が空のときに限り bozo を失敗扱いとする。
        if getattr(feed, "bozo", False) and not feed.entries:
            bozo_exc = getattr(feed, "bozo_exception", None)
            print(f"  connpass RSS ({label}): RSS パース失敗 ({bozo_exc})")
            return collected, False
        for entry in feed.entries:
            url = entry.get("link", "")
            if not url or url in seen_urls:
                continue
            # 想定外ホスト/パスの URL（SSRF / 表示崩れの原因）は破棄する。
            if not _is_connpass_event_url(url):
                continue
            title = entry.get("title", "").strip()
            desc = entry.get("summary", "").strip()
            if not _is_it_event(title, desc):
                continue
            started_at = _parse_started_at(entry)
            # started_at が無いイベントはカレンダー上に表示できないため除外する。
            if not started_at:
                continue
            # 開催日（日付部分）が今日より前のイベントをスキップ。
            # 当日開始のイベントは開始時刻に関わらず表示対象とする。
            if started_at[:10] < today_str:
                continue
            seen_urls.add(url)
            collected.append({
                "title": title,
                "event_url": url,
                "started_at": started_at,
                "place": place,
                "catch": desc[:200],
            })
        print(f"  connpass RSS ({label}): {len(collected)} 件取得")
    except Exception as e:
        print(f"  connpass RSS ({label}): 取得失敗 ({e})")
        return collected, False
    return collected, True


def fetch_vendor_news_events(today: datetime) -> list[dict]:
    """大手ベンダー・大規模コミュニティカンファレンスの最新情報を Google News RSS から取得する。

    VENDOR_EVENT_NEWS_FEEDS に定義された各カンファレンス（Microsoft Build / Ignite、
    AWS Summit / re:Invent、Google Cloud Next、KubeCon 等）の最新ニュース記事を取得し、
    記事の公開日をカレンダー表示日として events.json に追加する。

    connpass イベントと異なり、ベンダーイベントニュースは公開日が今日より前の記事も
    収集対象とする（直近のカンファレンス情報や参加レポートも含めたいため）。

    これにより、カレンダー上でベンダーイベント関連の最新情報が公開された日付を
    ひと目で確認できるようになる。各エントリには「ベンダーイベント情報」であることを
    示す place フィールドおよび vendor_event フラグが設定される。

    取得失敗は警告のみでスキップし、connpass 系の取得には影響しない。
    """
    # today は将来の拡張（例: 取得日時のログ出力）のために保持する
    _ = today
    events: list[dict] = []
    seen_urls: set[str] = set()

    for feed_info in VENDOR_EVENT_NEWS_FEEDS:
        name = feed_info["name"]
        url = feed_info["url"]
        place = feed_info.get("place", "")
        count = 0
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if getattr(feed, "bozo", False) and not feed.entries:
                print(f"  ベンダーイベント RSS ({name}): RSS パース失敗")
                continue
            for entry in feed.entries[:_VENDOR_EVENT_MAX_ENTRIES_PER_FEED]:
                article_url = entry.get("link", "")
                if not article_url or article_url in seen_urls:
                    continue
                title = entry.get("title", "").strip()
                desc = entry.get("summary", "").strip()
                if not title:
                    continue
                started_at = _parse_started_at(entry)
                # 公開日（started_at）が取得できない場合はカレンダーに表示できないためスキップ
                if not started_at:
                    continue
                seen_urls.add(article_url)
                events.append({
                    "title": f"[{name}] {title}",
                    "event_url": article_url,
                    "started_at": started_at,
                    "place": place,
                    "catch": desc[:200],
                    "vendor_event": True,
                })
                count += 1
            print(f"  ベンダーイベント RSS ({name}): {count} 件取得")
        except Exception as e:
            print(f"  ベンダーイベント RSS ({name}): 取得失敗 ({e})")

    return events


def fetch_events(today: datetime) -> list[dict]:
    """今日以降のイベントを connpass RSS から取得し、ベンダーイベント情報を追加する。

    関東（東京都・神奈川県）の pref_id 検索とオンライン（online=1）検索の
    2 系統で connpass イベントを取得し、さらに大手ベンダー・大規模カンファレンスの
    最新ニュースを Google News RSS から取得して合わせて返す。
    重複を排除して日時昇順に返す。

    全 connpass RSS 取得が失敗した場合は :class:`RuntimeError` を送出する
    （docs/events.json を空で上書きしないため）。
    """
    today_str = today.strftime("%Y/%m/%d")
    months = _build_search_months(today, CALENDAR_LOOKAHEAD_MONTHS)

    events: list[dict] = []
    seen_urls: set[str] = set()
    attempts = 0
    failures = 0

    # --- 都道府県別検索 ---
    for pref, pref_id in _PREFECTURE_IDS.items():
        for ym in months:
            collected, ok = _fetch_rss_events(
                params={"format": "rss", "pref_id": pref_id, "ym": ym},
                place=pref,
                today_str=today_str,
                seen_urls=seen_urls,
                label=f"{pref} {ym}",
            )
            attempts += 1
            if not ok:
                failures += 1
            events.extend(collected)

    # --- オンラインイベント検索 ---
    for ym in months:
        collected, ok = _fetch_rss_events(
            params={"format": "rss", "online": 1, "ym": ym},
            place="オンライン",
            today_str=today_str,
            seen_urls=seen_urls,
            label=f"オンライン {ym}",
        )
        attempts += 1
        if not ok:
            failures += 1
        events.extend(collected)

    # 全リクエスト失敗時は例外（既存 events.json の上書き防止）
    if attempts > 0 and failures == attempts:
        raise RuntimeError(
            f"connpass RSS 取得が全 {attempts} 件失敗しました。"
            "既存の docs/events.json を保持するため処理を中断します。"
        )

    # --- 大手ベンダー・大規模カンファレンス情報 ---
    print("  ベンダーイベント情報を取得中...")
    vendor_events = fetch_vendor_news_events(today)
    # connpass と URL の重複がなければ追加（seen_urls は connpass 側のみ管理）
    for ev in vendor_events:
        if ev["event_url"] not in seen_urls:
            seen_urls.add(ev["event_url"])
            events.append(ev)
    print(f"  ベンダーイベント合計: {len(vendor_events)} 件")

    # 日時昇順ソート（日時不明は末尾）
    events.sort(
        key=lambda e: (0, e["started_at"]) if e.get("started_at") else (1, "")
    )

    if len(events) > MAX_CALENDAR_EVENTS:
        print(f"  ※ {len(events)} 件 → {MAX_CALENDAR_EVENTS} 件に制限")
        events = events[:MAX_CALENDAR_EVENTS]

    # connpass イベントページからイベント説明を取得（ベンダーイベントは対象外）
    _enrich_descriptions(events)

    return events


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    today = datetime.now(JST)
    print(f"イベントカレンダーデータ生成開始: {today.strftime('%Y-%m-%d %H:%M JST')}")

    try:
        events = fetch_events(today)
    except RuntimeError as e:
        # 全 RSS 取得失敗時は events.json を上書きせず非 0 終了
        # （前回データを保持しサイト上のイベント表示が消えないようにする）
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
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
