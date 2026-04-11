"""
デイリーアップデート生成スクリプト

複数の RSS/Atom フィードで最新ニュースを取得し、
GitHub Copilot (Claude Opus) / Azure OpenAI / OpenAI API でマークダウン記事を生成する。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests
from googlenewsdecoder import new_decoderv1
from openai import AzureOpenAI, OpenAI
from openai import OpenAIError

JST = timezone(timedelta(hours=9))

# --- ニュースソース定義 ---------------------------------------------------------------

FEEDS = {
    # --- Azure ---
    "azure": [
        {"name": "Azure Release Communications", "url": "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"},
        {"name": "Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
        {"name": "Google News Azure", "url": "https://news.google.com/rss/search?q=Azure+%E3%82%A2%E3%83%83%E3%83%97%E3%83%87%E3%83%BC%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
    ],
    # --- 技術系 (日本語) ---
    "tech_ja": [
        {"name": "ITmedia NEWS", "url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"},
        {"name": "GIGAZINE", "url": "https://gigazine.net/news/rss_2.0/"},
        {"name": "Publickey", "url": "https://www.publickey1.jp/atom.xml"},
        {"name": "INTERNET Watch", "url": "https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf"},
        {"name": "Zenn トレンド", "url": "https://zenn.dev/feed"},
        {"name": "ITmedia テクノロジー", "url": "https://rss.itmedia.co.jp/rss/2.0/news_technology.xml"},
        {"name": "PC Watch", "url": "https://pc.watch.impress.co.jp/data/rss/1.0/pcw/feed.rdf"},
        {"name": "DevelopersIO", "url": "https://dev.classmethod.jp/feed/"},
        {"name": "日経クロステック IT", "url": "https://xtech.nikkei.com/rss/xtech-it.rdf"},
        {"name": "Impress Watch", "url": "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf"},
    ],
    # --- 技術系 (英語) ---
    "tech_en": [
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
        {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
        {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
        {"name": "Hacker News (Best)", "url": "https://hnrss.org/best"},
        {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
        {"name": "Wired", "url": "https://www.wired.com/feed/rss"},
        {"name": "The Register", "url": "https://www.theregister.com/headlines.atom"},
        {"name": "ZDNet", "url": "https://www.zdnet.com/news/rss.xml"},
        {"name": "Dev.to", "url": "https://dev.to/feed"},
        {"name": "Slashdot", "url": "https://slashdot.org/index.rss"},
    ],
    # --- ビジネス系 (日本語) ---
    "business_ja": [
        {"name": "NHK ビジネス", "url": "https://www.nhk.or.jp/rss/news/cat4.xml"},
        {"name": "東洋経済オンライン", "url": "https://toyokeizai.net/list/feed/rss"},
        {"name": "ITmedia エンタープライズ", "url": "https://rss.itmedia.co.jp/rss/2.0/enterprise.xml"},
        {"name": "Google News 経済", "url": "https://news.google.com/rss/search?q=%E7%B5%8C%E6%B8%88+%E3%83%93%E3%82%B8%E3%83%8D%E3%82%B9&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News IT企業", "url": "https://news.google.com/rss/search?q=IT%E4%BC%81%E6%A5%AD+%E3%82%B9%E3%82%BF%E3%83%BC%E3%83%88%E3%82%A2%E3%83%83%E3%83%97&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News AI", "url": "https://news.google.com/rss/search?q=AI+%E4%BA%BA%E5%B7%A5%E7%9F%A5%E8%83%BD+%E6%96%B0%E6%A9%9F%E8%83%BD&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News DX", "url": "https://news.google.com/rss/search?q=DX+%E3%83%87%E3%82%B8%E3%82%BF%E3%83%AB%E3%83%88%E3%83%A9%E3%83%B3%E3%82%B9%E3%83%95%E3%82%A9%E3%83%BC%E3%83%A1%E3%83%BC%E3%82%B7%E3%83%A7%E3%83%B3&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News スタートアップ", "url": "https://news.google.com/rss/search?q=%E3%82%B9%E3%82%BF%E3%83%BC%E3%83%88%E3%82%A2%E3%83%83%E3%83%97+%E8%B3%87%E9%87%91%E8%AA%BF%E9%81%94+IT&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News 半導体", "url": "https://news.google.com/rss/search?q=%E5%8D%8A%E5%B0%8E%E4%BD%93+%E3%83%86%E3%82%AF%E3%83%8E%E3%83%AD%E3%82%B8%E3%83%BC&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News サイバーセキュリティ", "url": "https://news.google.com/rss/search?q=%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3+%E8%84%86%E5%BC%B1%E6%80%A7&hl=ja&gl=JP&ceid=JP:ja"},
    ],
    # --- ビジネス系 (英語) ---
    "business_en": [
        {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
        {"name": "CNBC Tech", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"},
        {"name": "Google News (Reuters Business)", "url": "https://news.google.com/rss/search?q=business+technology+site:reuters.com&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (Bloomberg Tech)", "url": "https://news.google.com/rss/search?q=technology+site:bloomberg.com&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (Financial Times)", "url": "https://news.google.com/rss/search?q=technology+business+site:ft.com&hl=en&gl=US&ceid=US:en"},
        {"name": "WSJ Tech", "url": "https://feeds.a.dj.com/rss/RSSWSJD.xml"},
        {"name": "Google News (Cloud Computing)", "url": "https://news.google.com/rss/search?q=cloud+computing+AWS+Azure+GCP&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (AI Business)", "url": "https://news.google.com/rss/search?q=artificial+intelligence+business&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (Startup Funding)", "url": "https://news.google.com/rss/search?q=startup+funding+technology&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (Semiconductor)", "url": "https://news.google.com/rss/search?q=semiconductor+chip+technology&hl=en&gl=US&ceid=US:en"},
    ],
    # --- SNS / トレンド ---
    "sns": [
        {"name": "はてなブックマーク IT", "url": "https://b.hatena.ne.jp/hotentry/it.rss"},
        {"name": "Reddit Technology", "url": "https://www.reddit.com/r/technology/.rss"},
        {"name": "Reddit Programming", "url": "https://www.reddit.com/r/programming/.rss"},
        {"name": "X(Twitter) IT話題 (国内)", "url": "https://news.google.com/rss/search?q=X+Twitter+IT+%E8%A9%B1%E9%A1%8C+%E3%83%88%E3%83%AC%E3%83%B3%E3%83%89&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "X(Twitter) Tech Trends", "url": "https://news.google.com/rss/search?q=twitter+X+trending+tech&hl=en&gl=US&ceid=US:en"},
        {"name": "Reddit DevOps", "url": "https://www.reddit.com/r/devops/.rss"},
        {"name": "Reddit SysAdmin", "url": "https://www.reddit.com/r/sysadmin/.rss"},
        {"name": "Qiita トレンド", "url": "https://qiita.com/popular-items/feed"},
        {"name": "Reddit Artificial Intelligence", "url": "https://www.reddit.com/r/artificial/.rss"},
        {"name": "Reddit Cloud Computing", "url": "https://www.reddit.com/r/cloudcomputing/.rss"},
    ],
    # --- IT運用・管理 ---
    "itops": [
        {"name": "Microsoft Tech Community - IT Ops", "url": "https://techcommunity.microsoft.com/plugins/custom/microsoft/o365/custom-blog-rss?tid=8&board=ITOpsTalkBlog"},
        {"name": "Reddit SysAdmin", "url": "https://www.reddit.com/r/sysadmin/.rss"},
        {"name": "Reddit DevOps", "url": "https://www.reddit.com/r/devops/.rss"},
        {"name": "Google News AIOps EN", "url": "https://news.google.com/rss/search?q=AIOps+AI+operations&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News AIOps JP", "url": "https://news.google.com/rss/search?q=AIOps+%E9%81%8B%E7%94%A8+AI&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News IT運用", "url": "https://news.google.com/rss/search?q=IT%E9%81%8B%E7%94%A8+%E7%AE%A1%E7%90%86+%E8%87%AA%E5%8B%95%E5%8C%96&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News IT Operations Management", "url": "https://news.google.com/rss/search?q=IT+operations+management+automation&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News Azure Monitor AIOps", "url": "https://news.google.com/rss/search?q=Azure+Monitor+AIOps+observability&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News Microsoft Intune", "url": "https://news.google.com/rss/search?q=Microsoft+Intune+endpoint+management&hl=en&gl=US&ceid=US:en"},
        {"name": "InfoQ DevOps", "url": "https://feed.infoq.com/DevOps"},
        {"name": "Reddit MSP (Managed Service Providers)", "url": "https://www.reddit.com/r/msp/.rss"},
        {"name": "Google News ITSM", "url": "https://news.google.com/rss/search?q=ITSM+ServiceNow+IT+service+management&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News Observability", "url": "https://news.google.com/rss/search?q=observability+monitoring+AIOps+OpenTelemetry&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News SRE Agent EN", "url": "https://news.google.com/rss/search?q=SRE+agent+AI+site+reliability+engineering&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News SRE Agent JP", "url": "https://news.google.com/rss/search?q=SRE+%E3%82%A8%E3%83%BC%E3%82%B8%E3%82%A7%E3%83%B3%E3%83%88+AI+%E3%82%B5%E3%82%A4%E3%83%88%E4%BF%A1%E9%A0%BC%E6%80%A7&hl=ja&gl=JP&ceid=JP:ja"},
    ],
    # --- コミュニティイベント参加レポ ---
    "event_reports": [
        {"name": "Google News connpass 参加レポ", "url": "https://news.google.com/rss/search?q=connpass+%E5%8F%82%E5%8A%A0+%E3%83%AC%E3%83%9D+%E6%9D%B1%E4%BA%AC+%E7%A5%9E%E5%A5%88%E5%B7%9D&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News 勉強会 参加レポ 東京", "url": "https://news.google.com/rss/search?q=%E5%8B%89%E5%BC%B7%E4%BC%9A+%E5%8F%82%E5%8A%A0%E3%83%AC%E3%83%9D+%E6%9D%B1%E4%BA%AC&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Zenn connpass イベント", "url": "https://zenn.dev/feed?topicname=connpass"},
        {"name": "Qiita connpass", "url": "https://qiita.com/tags/connpass/feed"},
        {"name": "はてなブックマーク 勉強会", "url": "https://b.hatena.ne.jp/q/%E5%8B%89%E5%BC%B7%E4%BC%9A%20%E5%8F%82%E5%8A%A0%E3%83%AC%E3%83%9D?mode=rss&sort=hot"},
    ],
}

HTTP_HEADERS = {
    "User-Agent": "daily-updates-bot/1.0 (GitHub Actions; +https://github.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
}


# --- URL 解決 -------------------------------------------------------------------


def _resolve_google_news_url(url: str) -> str:
    """Google News RSS のリダイレクト URL を実際の記事 URL に解決する。"""
    if "news.google.com/rss/articles/" not in url:
        return url
    try:
        result = new_decoderv1(url)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception as e:
        print(f"    URL 解決失敗 ({url}): {e}")
    return url


# --- リンク検証 ---------------------------------------------------------------

# RSS / Atom フィードを示す Content-Type
_RSS_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
)


def _validate_url(url: str) -> tuple[bool, str]:
    """単一 URL を検証し、(OK, 理由) を返す。"""
    try:
        resp = requests.head(
            url,
            headers={"User-Agent": HTTP_HEADERS["User-Agent"]},
            timeout=10,
            allow_redirects=True,
        )
        # HEAD が 405 の場合は GET でリトライ
        if resp.status_code == 405:
            resp = requests.get(
                url,
                headers={"User-Agent": HTTP_HEADERS["User-Agent"]},
                timeout=10,
                allow_redirects=True,
                stream=True,
            )
            content_type = resp.headers.get("Content-Type", "")
            resp.close()
        else:
            content_type = resp.headers.get("Content-Type", "")

        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"

        # RSS/Atom ページへのリンクを検出
        ct_lower = content_type.lower().split(";")[0].strip()
        if ct_lower in _RSS_CONTENT_TYPES:
            return False, f"RSS/Atom フィード ({ct_lower})"

        # Google News のリダイレクト URL がそのまま残っている場合
        if "news.google.com/rss/articles/" in resp.url:
            return False, "Google News RSS リダイレクト URL"

        return True, "OK"
    except requests.RequestException as e:
        return False, f"接続エラー ({e.__class__.__name__})"


def _search_alternative_url(query: str) -> str | None:
    """Google News RSS で代替記事を検索し、最初の有効な URL を返す。"""
    search_url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    )
    try:
        resp = requests.get(
            search_url,
            headers=HTTP_HEADERS,
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:5]:
            raw_url = entry.get("link", "")
            resolved = _resolve_google_news_url(raw_url)
            if "news.google.com/rss/" in resolved:
                continue
            ok, _ = _validate_url(resolved)
            if ok:
                return resolved
    except Exception as e:
        print(f"    代替検索失敗: {e}")
    return None


def validate_links(markdown: str) -> str:
    """マークダウン内の全リンクを検証し、代替ソースの検索またはトピック除去を行う。"""
    link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^)]+)\)')
    matches = link_pattern.findall(markdown)

    if not matches:
        return markdown

    # 重複する URL を除いて検証対象を抽出
    seen_urls: set[str] = set()
    unique_checks: list[tuple[str, str]] = []
    for text, url in matches:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_checks.append((text, url))

    print(f"  リンク検証: {len(unique_checks)} 件の URL をチェック中...")

    invalid_urls: dict[str, str] = {}  # url -> reason
    for _text, url in unique_checks:
        ok, reason = _validate_url(url)
        if not ok:
            invalid_urls[url] = reason
            print(f"    ✗ {url[:80]} — {reason}")

    if not invalid_urls:
        print("  リンク検証: 全てのリンクが有効です")
        return markdown

    print(f"  リンク検証: {len(invalid_urls)} 件の無効リンクを検出、代替ソースを検索中...")

    # 無効リンクごとに代替 URL を検索
    replacement_urls: dict[str, str] = {}  # original_url -> alternative_url
    unfixable_urls: set[str] = set()

    for text, url in matches:
        if url not in invalid_urls:
            continue
        if url in replacement_urls or url in unfixable_urls:
            continue

        print(f"    🔍 代替検索: {text[:60]}...")
        alt = _search_alternative_url(text)
        if alt:
            replacement_urls[url] = alt
            print(f"       → 代替: {alt[:80]}")
        else:
            unfixable_urls.add(url)
            print(f"       → 代替なし（トピックを除去します）")

    # 1) 代替 URL が見つかったリンクを置換
    def _replace_link(m: re.Match) -> str:
        text = m.group(1)
        url = m.group(2)
        if url in replacement_urls:
            return f"[{text}]({replacement_urls[url]})"
        return m.group(0)

    result = link_pattern.sub(_replace_link, markdown)

    # 2) 代替が見つからなかったリンクを含むトピックブロックを除去
    if unfixable_urls:
        for url in unfixable_urls:
            # トピックブロック: ### 見出し から次の ### or ## or --- まで
            escaped = re.escape(url)
            topic_pattern = re.compile(
                r'### [^\n]+\n'         # ### 見出し行
                r'(?:(?!###\s|##\s|---).)*?'  # 見出し以外の内容
                rf'(?:\[([^\]]*)\]\({escaped}\)|{escaped})'  # 無効 URL を含む行
                r'(?:(?!###\s|##\s|---).)*',  # トピック末尾まで
                re.DOTALL,
            )
            result = topic_pattern.sub('', result)

        # 連続する空行を整理
        result = re.sub(r'\n{3,}', '\n\n', result)

    removed = len(unfixable_urls)
    replaced = len(replacement_urls)
    print(f"  リンク検証完了: 代替リンク={replaced} 件, トピック除去={removed} 件")

    print(f"  リンク検証完了: 代替リンク={replaced} 件, トピック除去={removed} 件")
    return result


# --- フィード取得 -----------------------------------------------------------------


def _fetch_feed(url: str, since: datetime, max_items: int = 10) -> list[dict]:
    """単一の RSS/Atom フィードを取得し、since 以降の記事を返す。"""
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    articles = []
    for entry in feed.entries:
        # 公開日時のパース
        pub_date = None
        for attr in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, attr, None)
            if parsed:
                try:
                    pub_date = datetime(*parsed[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
                break

        if pub_date and pub_date < since:
            continue

        article_url = _resolve_google_news_url(entry.get("link", ""))
        articles.append(
            {
                "title": entry.get("title", "").strip(),
                "description": entry.get("summary", "").strip()[:150],
                "url": article_url,
                "datePublished": str(pub_date) if pub_date else "",
            }
        )
        if len(articles) >= max_items:
            break

    return articles


def fetch_category(category: str, since: datetime) -> list[dict]:
    """カテゴリに属する全フィードから記事を収集する。"""
    all_articles = []
    for source in FEEDS.get(category, []):
        try:
            items = _fetch_feed(source["url"], since)
            for item in items:
                item["source"] = source["name"]
            all_articles.extend(items)
            print(f"    {source['name']}: {len(items)} 件")
        except Exception as e:
            print(f"    {source['name']}: 取得失敗 ({e})")
    return all_articles


CONNPASS_API_URL = "https://connpass.com/api/v1/event/"
CONNPASS_TARGET_PREFECTURES = ["tokyo", "kanagawa"]
# 取得する最大イベント数
CONNPASS_MAX_EVENTS = 20
# 先読み日数（今日から何日先まで）
CONNPASS_LOOKAHEAD_DAYS = 60


def fetch_connpass_events(target_date: str) -> list[dict]:
    """connpassから東京・神奈川の近日開催コミュニティイベントを取得する。

    申し込みが開始されていて、まだ申し込み可能な（開催前の）イベントを返す。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    cutoff_dt = target_dt + timedelta(days=CONNPASS_LOOKAHEAD_DAYS)

    all_events: list[dict] = []
    # (event_dt, event_dict) のリストで収集し、後でdatetimeでソートする
    events_with_dt: list[tuple] = []

    for pref in CONNPASS_TARGET_PREFECTURES:
        params = {
            "prefectures": pref,
            "count": CONNPASS_MAX_EVENTS,
            "order": 2,  # 開催日順
        }
        try:
            resp = requests.get(
                CONNPASS_API_URL,
                params=params,
                headers=HTTP_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            print(f"    connpass ({pref}): {data.get('results_returned', 0)} 件取得")

            for event in data.get("events", []):
                # 参加受付型のみ対象（"advertisement" は申し込み不可）
                if event.get("event_type") != "participation":
                    continue

                started_at_str = event.get("started_at", "")
                if not started_at_str:
                    continue

                try:
                    # ISO 8601 形式をパース
                    event_dt = datetime.fromisoformat(
                        started_at_str.replace("Z", "+00:00")
                    ).astimezone(JST)
                except (ValueError, TypeError):
                    continue

                # 今日以降、先読み範囲内のイベントのみ
                if event_dt < target_dt or event_dt > cutoff_dt:
                    continue

                accepted = event.get("accepted", 0) or 0
                limit = event.get("limit", 0) or 0

                # 定員が設定されていて満員のイベントは除外
                if limit > 0 and accepted >= limit:
                    continue

                series_title = ""
                if isinstance(event.get("series"), dict):
                    series_title = event["series"].get("title", "")

                events_with_dt.append((event_dt, {
                    "title": event.get("title", "").strip(),
                    "catch": event.get("catch", "").strip(),
                    "event_url": event.get("event_url", ""),
                    "started_at": event_dt.strftime("%Y/%m/%d %H:%M"),
                    "place": event.get("place", "").strip(),
                    "address": event.get("address", "").strip(),
                    "accepted": accepted,
                    "limit": limit,
                    "series": series_title,
                }))
        except Exception as e:
            print(f"    connpass ({pref}): 取得失敗 ({e})")

    # 開催日時でソート（datetime オブジェクトを使用）
    events_with_dt.sort(key=lambda x: x[0])
    all_events = [ev for _, ev in events_with_dt]
    if len(all_events) > CONNPASS_MAX_EVENTS:
        print(f"  ※ connpass {len(all_events)} 件 → {CONNPASS_MAX_EVENTS} 件に制限")
        all_events = all_events[:CONNPASS_MAX_EVENTS]

    return all_events


# カテゴリ別の記事数上限（プロンプトサイズ制御用）
MAX_ARTICLES = {
    "azure": 20,
    "tech": 30,
    "business": 30,
    "sns": 20,
    "itops": 20,
    "event_reports": 15,
}


def _limit_articles(articles: list[dict], category: str) -> list[dict]:
    """記事リストをカテゴリ上限に制限する。"""
    limit = MAX_ARTICLES.get(category, 10)
    if len(articles) > limit:
        print(f"  ※ {len(articles)} 件 → {limit} 件に制限")
    return articles[:limit]


# --- LLM クライアント -----------------------------------------------------------


GITHUB_MODELS_CANDIDATES = [
    "gpt-4o",
    "gpt-4o-mini",
]


def create_llm_clients() -> list[tuple]:
    """環境変数に応じて利用可能な LLM クライアントを優先順に返す。"""
    clients = []

    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        gh_client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=github_token,
        )
        for model_name in GITHUB_MODELS_CANDIDATES:
            clients.append((gh_client, model_name))

    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        clients.append((
            AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=api_key,
                api_version="2024-12-01-preview",
            ),
            os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        ))

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        clients.append((OpenAI(api_key=openai_api_key), "gpt-4o"))

    if not clients:
        raise RuntimeError(
            "LLM の認証情報が見つかりません。"
            "GITHUB_TOKEN, OPENAI_API_KEY, または AZURE_OPENAI_ENDPOINT を設定してください。"
        )
    return clients


def create_llm_client() -> tuple:
    """環境変数に応じて GitHub Models / Azure OpenAI / OpenAI クライアントを生成する。"""
    return create_llm_clients()[0]


# --- 記事生成 -------------------------------------------------------------------

# セクションごとの LLM 呼び出し定義
# 各セクションは独立した API コールで生成し、トークンを最大限に活用する。
SECTION_DEFINITIONS = [
    {
        "key": "azure",
        "system": (
            "あなたは Microsoft Azure の専門ライターです。"
            "提供された Azure ニュースを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の Azure 関連ニュースから 5〜6 個のトピックを選定し、マークダウン形式で出力してください。\n"
            "先頭に「## 1. Azure アップデート情報」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "Azure 関連ニュース",
    },
    {
        "key": "tech",
        "system": (
            "あなたは IT・テクノロジーニュースの専門ライターです。"
            "提供されたニュースを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の技術系ニュース（日本語・英語混在）から IT・テクノロジー関連トピックを 5〜6 個選定し、"
            "マークダウン形式で出力してください。\n"
            "先頭に「## 2. ニュースで話題のテーマ」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "技術系ニュース（日本語 + 英語ソース）",
    },
    {
        "key": "sns",
        "system": (
            "あなたは SNS・トレンドニュースの専門ライターです。"
            "提供されたニュースを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の SNS・トレンド情報（はてブ・Reddit 等）から 5〜6 個のトピックを選定し、"
            "マークダウン形式で出力してください。\n"
            "先頭に「## 3. SNSで話題のテーマ」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "SNS / トレンド（はてブ・Reddit）",
    },
    {
        "key": "business",
        "system": (
            "あなたはビジネスニュースの専門ライターです。"
            "提供されたニュースを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下のビジネスニュース（日本語・英語混在）から IT 以外のトピックを 5〜6 個選定し、"
            "マークダウン形式で出力してください。\n"
            "世界情勢、経済・金融、政治、社会問題、産業動向など IT 以外のビジネス話題を選定してください。"
            "IT企業の決算・AI・半導体など IT 関連はこのセクションに含めないでください。\n"
            "先頭に「## 4. ビジネスホットトピック」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "ビジネスニュース（日本語 + 英語ソース）",
    },
    {
        "key": "itops",
        "system": (
            "あなたは IT 運用・管理の専門ライターです。"
            "提供されたニュースを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の IT 運用・管理ニュースから 3〜5 個のトピックを選定し、マークダウン形式で出力してください。\n"
            "**AIOps**（AIを活用したIT運用自動化・異常検知・予測分析）および"
            "**SRE Agent**（AI駆動のサイト信頼性エンジニアリングエージェント）を重点的に取り上げてください。"
            "Microsoft Azure Monitor・System Center 等の Microsoft 製品による AIOps も優先的に含めてください。"
            "ITSM・DevOps・エンドポイント管理・MSP・オブザーバビリティなど IT 運用全般のトレンドも含めてください。\n"
            "先頭に「## 5. IT運用・管理」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "IT運用・管理（AIOps / ITSM / DevOps / エンドポイント管理）",
    },
    {
        "key": "community",
        "system": (
            "あなたはコミュニティイベント情報の専門ライターです。"
            "提供されたデータを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の connpass イベントデータと参加レポートを元に"
            "「## 6. コミュニティイベント情報（東京・神奈川）」セクションを作成してください。\n\n"
            "先頭に「## 6. コミュニティイベント情報（東京・神奈川）」を出力し、"
            "以下の 2 サブセクション構成で出力してください。\n\n"
            "### 📅 申し込み受付中のイベント\n\n"
            "connpass イベントデータから申し込み可能な近日開催イベントを箇条書きで列挙してください。"
            "各イベントに「イベント名（リンク付き）」「開催日時」「場所」「概要」"
            "「参加状況（申込数/定員）」を記載してください。"
            "イベントデータが空の場合は「現在取得できるイベント情報はありません」と記載してください。\n\n"
            "### 📝 参加レポート・まとめ\n\n"
            "参加レポートデータから最近の勉強会・コミュニティイベントの参加レポートや開催レポートをまとめてください。"
            "各レポートは見出し・要約・参考リンクで構成してください。"
            "レポートが少ない場合は取得できた範囲で記載してください。\n\n"
            "コードブロックで囲まないこと。"
        ),
        # community セクションは複数のデータソースを持つため data_label は使用しない
        "data_label": None,
    },
]

# セクションごとの入力トークン上限（1 トークン ≈ 2.5 文字として概算）
SECTION_MAX_INPUT_CHARS = {
    "azure": 30_000,
    "tech": 40_000,
    "business": 40_000,
    "sns": 30_000,
    "itops": 30_000,
    "community": 20_000,
}

# セクションごとの出力トークン上限
SECTION_MAX_OUTPUT_TOKENS = 4096


def _build_section_prompt(section_def: dict, data: dict | list) -> str:
    """セクション固有のユーザープロンプトを組み立てる。

    data が dict の場合は {ラベル: ペイロード} の形式、
    list の場合は section_def["data_label"] を使ってラベルを付ける。
    """
    lines = [section_def["instruction"], ""]
    if isinstance(data, dict):
        for label, payload in data.items():
            lines.append(f"### {label}")
            lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
            lines.append("")
    else:
        label = section_def.get("data_label") or "データ"
        lines.append(f"### {label}")
        lines.append(json.dumps(data, ensure_ascii=False, indent=2))
        lines.append("")
    return "\n".join(lines)


def generate_section(
    client,
    model: str,
    section_def: dict,
    data: dict | list,
) -> str:
    """1 セクション分の記事を LLM で生成する。"""
    key = section_def["key"]
    max_input = SECTION_MAX_INPUT_CHARS.get(key, 30_000)

    # 入力が大きすぎる場合はリストを末尾から削減する
    if isinstance(data, dict):
        all_lists = [v for v in data.values() if isinstance(v, list)]
    else:
        all_lists = [data] if isinstance(data, list) else []

    user_prompt = _build_section_prompt(section_def, data)
    while len(user_prompt) > max_input:
        trimmed = False
        for lst in all_lists:
            if len(lst) > 3:
                lst.pop()
                trimmed = True
        if not trimmed:
            break
        user_prompt = _build_section_prompt(section_def, data)

    print(f"    入力: 約 {len(user_prompt):,} 文字")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": section_def["system"]},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=SECTION_MAX_OUTPUT_TOKENS,
    )
    return response.choices[0].message.content.strip()


def generate_article(
    client,
    model: str,
    target_date: str,
    azure_news: list[dict],
    tech_news: list[dict],
    business_news: list[dict],
    sns_news: list[dict],
    itops_news: list[dict],
    connpass_events: list[dict],
    event_reports: list[dict],
) -> str:
    """各セクションを個別の LLM 呼び出しで生成し、1 つの記事に組み立てる。

    セクションごとに独立した API コールを行うことで、各セクションが
    トークン上限を最大限に活用できるようにする。
    """
    formatted_date = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:]}"

    section_data_map: dict[str, dict | list] = {
        "azure": azure_news,
        "tech": tech_news,
        "sns": sns_news,
        "business": business_news,
        "itops": itops_news,
        "community": {
            "connpass イベント（東京・神奈川、申し込み受付中）": connpass_events,
            "コミュニティイベント参加レポート": event_reports,
        },
    }

    article_parts = [f"# {formatted_date} デイリーアップデート"]

    for section_def in SECTION_DEFINITIONS:
        key = section_def["key"]
        data = section_data_map[key]
        print(f"  [{key}] セクション生成中...")
        section_text = generate_section(client, model, section_def, data)
        article_parts.append(section_text)

    return "\n\n".join(article_parts)


# --- メイン処理 -----------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_daily_update.py YYYYMMDD")
        sys.exit(1)

    target_date = sys.argv[1]
    # 前日 8:00 JST 以降の記事を対象とする
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    since = target_dt - timedelta(days=1) + timedelta(hours=8)

    print(f"対象日: {target_date}")
    print(f"収集期間: {since.isoformat()} 以降")
    print("ニュースを取得中...")

    print("\n[Azure]")
    azure_news = _limit_articles(fetch_category("azure", since), "azure")
    print(f"  → 合計: {len(azure_news)} 件")

    print("\n[技術系 日本語]")
    tech_ja = fetch_category("tech_ja", since)
    print(f"  → 合計: {len(tech_ja)} 件")

    print("\n[技術系 英語]")
    tech_en = fetch_category("tech_en", since)
    print(f"  → 合計: {len(tech_en)} 件")

    tech_news = _limit_articles(tech_ja + tech_en, "tech")

    print("\n[ビジネス系 日本語]")
    biz_ja = fetch_category("business_ja", since)
    print(f"  → 合計: {len(biz_ja)} 件")

    print("\n[ビジネス系 英語]")
    biz_en = fetch_category("business_en", since)
    print(f"  → 合計: {len(biz_en)} 件")

    business_news = _limit_articles(biz_ja + biz_en, "business")

    print("\n[SNS / トレンド]")
    sns_news = _limit_articles(fetch_category("sns", since), "sns")
    print(f"  → 合計: {len(sns_news)} 件")

    print("\n[IT運用・管理]")
    itops_news = _limit_articles(fetch_category("itops", since), "itops")
    print(f"  → 合計: {len(itops_news)} 件")

    print("\n[connpass イベント（東京・神奈川）]")
    connpass_events = fetch_connpass_events(target_date)
    print(f"  → 合計: {len(connpass_events)} 件")

    print("\n[コミュニティイベント参加レポート]")
    event_reports = _limit_articles(fetch_category("event_reports", since), "event_reports")
    print(f"  → 合計: {len(event_reports)} 件")

    print("\n記事を生成中（セクションごとに個別生成）...")
    llm_clients = create_llm_clients()
    article = None
    last_error = None
    for client, model in llm_clients:
        try:
            print(f"  モデル: {model}")
            article = generate_article(
                client, model, target_date, azure_news, tech_news, business_news, sns_news, itops_news,
                connpass_events, event_reports,
            )
            break
        except OpenAIError as e:
            print(f"  ⚠ {model} での生成に失敗しました ({e})")
            last_error = e
    if article is None:
        raise RuntimeError(f"全ての LLM プロバイダーで生成に失敗しました。最後のエラー: {last_error}")

    print("\nリンクを検証中...")
    article = validate_links(article)

    output_dir = "updates"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
