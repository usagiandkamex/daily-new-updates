"""
テクニカル雑談生成スクリプト

SNS を中心に IT 関連の話題を収集し、
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
    # --- Microsoft ---
    "microsoft": [
        {"name": "Reddit Microsoft", "url": "https://www.reddit.com/r/microsoft/.rss"},
        {"name": "Reddit Windows", "url": "https://www.reddit.com/r/Windows11/.rss"},
        {"name": "はてなブックマーク Microsoft", "url": "https://b.hatena.ne.jp/search/tag?q=Microsoft&mode=rss"},
        {"name": "X(Twitter) Microsoft話題", "url": "https://news.google.com/rss/search?q=Microsoft+%E8%A9%B1%E9%A1%8C&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Microsoft", "url": "https://news.google.com/rss/search?q=Microsoft+latest&hl=en&gl=US&ceid=US:en"},
        {"name": "Reddit Surface", "url": "https://www.reddit.com/r/Surface/.rss"},
        {"name": "Publickey", "url": "https://www.publickey1.jp/atom.xml"},
        {"name": "Qiita Microsoft", "url": "https://qiita.com/tags/microsoft/feed"},
        {"name": "Google News Microsoft Japan", "url": "https://news.google.com/rss/search?q=Microsoft+%E6%97%A5%E6%9C%AC&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Windows", "url": "https://news.google.com/rss/search?q=Windows+update+new&hl=en&gl=US&ceid=US:en"},
    ],
    # --- AI ---
    "ai": [
        {"name": "Reddit MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss"},
        {"name": "Reddit LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/.rss"},
        {"name": "はてなブックマーク AI", "url": "https://b.hatena.ne.jp/search/tag?q=AI&mode=rss"},
        {"name": "X(Twitter) AI話題", "url": "https://news.google.com/rss/search?q=AI+%E4%BA%BA%E5%B7%A5%E7%9F%A5%E8%83%BD+%E8%A9%B1%E9%A1%8C&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Hacker News AI", "url": "https://hnrss.org/best?q=AI+LLM"},
        {"name": "Reddit Artificial", "url": "https://www.reddit.com/r/artificial/.rss"},
        {"name": "Reddit OpenAI", "url": "https://www.reddit.com/r/OpenAI/.rss"},
        {"name": "Qiita AI", "url": "https://qiita.com/tags/ai/feed"},
        {"name": "Zenn AI", "url": "https://zenn.dev/topics/ai/feed"},
        {"name": "Google News AI Business", "url": "https://news.google.com/rss/search?q=artificial+intelligence+business&hl=en&gl=US&ceid=US:en"},
    ],
    # --- Azure ---
    "azure": [
        {"name": "Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
        {"name": "Azure Release Communications", "url": "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"},
        {"name": "Reddit Azure", "url": "https://www.reddit.com/r/azure/.rss"},
        {"name": "X(Twitter) Azure話題", "url": "https://news.google.com/rss/search?q=Azure+%E8%A9%B1%E9%A1%8C&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Azure", "url": "https://news.google.com/rss/search?q=Azure+cloud&hl=en&gl=US&ceid=US:en"},
        {"name": "Azure SDK Blog", "url": "https://devblogs.microsoft.com/azure-sdk/feed/"},
        {"name": "Qiita Azure", "url": "https://qiita.com/tags/azure/feed"},
        {"name": "DevelopersIO", "url": "https://dev.classmethod.jp/feed/"},
        {"name": "Reddit CloudComputing", "url": "https://www.reddit.com/r/cloudcomputing/.rss"},
        {"name": "Google News Azure Japan", "url": "https://news.google.com/rss/search?q=Azure+%E3%82%A2%E3%83%83%E3%83%97%E3%83%87%E3%83%BC%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
    ],
    # --- セキュリティ ---
    "security": [
        {"name": "Reddit netsec", "url": "https://www.reddit.com/r/netsec/.rss"},
        {"name": "Reddit cybersecurity", "url": "https://www.reddit.com/r/cybersecurity/.rss"},
        {"name": "はてなブックマーク IT", "url": "https://b.hatena.ne.jp/hotentry/it.rss"},
        {"name": "X(Twitter) セキュリティ話題", "url": "https://news.google.com/rss/search?q=%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3+%E8%84%86%E5%BC%B1%E6%80%A7+IT&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Cybersecurity", "url": "https://news.google.com/rss/search?q=cybersecurity+vulnerability&hl=en&gl=US&ceid=US:en"},
        {"name": "Qiita セキュリティ", "url": "https://qiita.com/tags/security/feed"},
        {"name": "Reddit InfoSec", "url": "https://www.reddit.com/r/InfoSecNews/.rss"},
        {"name": "Google News サイバーセキュリティ JP", "url": "https://news.google.com/rss/search?q=%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E6%94%BB%E6%92%83+%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "INTERNET Watch", "url": "https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf"},
        {"name": "Slashdot Security", "url": "https://slashdot.org/index.rss"},
    ],
    # --- クラウド (Azure以外) ---
    "cloud": [
        {"name": "Reddit AWS", "url": "https://www.reddit.com/r/aws/.rss"},
        {"name": "Reddit GCP", "url": "https://www.reddit.com/r/googlecloud/.rss"},
        {"name": "Reddit CloudComputing", "url": "https://www.reddit.com/r/cloudcomputing/.rss"},
        {"name": "Qiita AWS", "url": "https://qiita.com/tags/aws/feed"},
        {"name": "Google News AWS", "url": "https://news.google.com/rss/search?q=AWS+Amazon+Web+Services&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News GCP", "url": "https://news.google.com/rss/search?q=Google+Cloud+Platform&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News OCI", "url": "https://news.google.com/rss/search?q=Oracle+Cloud+Infrastructure&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News クラウド JP", "url": "https://news.google.com/rss/search?q=AWS+GCP+%E3%82%AF%E3%83%A9%E3%82%A6%E3%83%89&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "DevelopersIO AWS", "url": "https://dev.classmethod.jp/feed/"},
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
}

HTTP_HEADERS = {
    "User-Agent": "daily-updates-bot/1.0 (GitHub Actions; +https://github.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
}

MAX_ARTICLES_PER_CATEGORY = 10

# カテゴリ別フィードが空の場合に使う汎用 IT ニュースフィード
GENERAL_NEWS_FEEDS = [
    {"name": "ITmedia NEWS", "url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"},
    {"name": "Publickey", "url": "https://www.publickey1.jp/atom.xml"},
    {"name": "GIGAZINE", "url": "https://gigazine.net/news/rss_2.0/"},
    {"name": "INTERNET Watch", "url": "https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf"},
    {"name": "DevelopersIO", "url": "https://dev.classmethod.jp/feed/"},
    {"name": "Zenn トレンド", "url": "https://zenn.dev/feed"},
    {"name": "Hacker News (Best)", "url": "https://hnrss.org/best"},
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
    {"name": "Google News IT 日本", "url": "https://news.google.com/rss/search?q=IT+%E6%8A%80%E8%A1%93+%E6%9C%80%E6%96%B0&hl=ja&gl=JP&ceid=JP:ja"},
]


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

        ct_lower = content_type.lower().split(";")[0].strip()
        if ct_lower in _RSS_CONTENT_TYPES:
            return False, f"RSS/Atom フィード ({ct_lower})"

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

    seen_urls: set[str] = set()
    unique_checks: list[tuple[str, str]] = []
    for text, url in matches:
        if url not in seen_urls:
            seen_urls.add(url)
            unique_checks.append((text, url))

    print(f"  リンク検証: {len(unique_checks)} 件の URL をチェック中...")

    invalid_urls: dict[str, str] = {}
    for _text, url in unique_checks:
        ok, reason = _validate_url(url)
        if not ok:
            invalid_urls[url] = reason
            print(f"    ✗ {url[:80]} — {reason}")

    if not invalid_urls:
        print("  リンク検証: 全てのリンクが有効です")
        return markdown

    print(f"  リンク検証: {len(invalid_urls)} 件の無効リンクを検出、代替ソースを検索中...")

    replacement_urls: dict[str, str] = {}
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

    def _replace_link(m: re.Match) -> str:
        text = m.group(1)
        url = m.group(2)
        if url in replacement_urls:
            return f"[{text}]({replacement_urls[url]})"
        return m.group(0)

    result = link_pattern.sub(_replace_link, markdown)

    if unfixable_urls:
        for url in unfixable_urls:
            escaped = re.escape(url)
            topic_pattern = re.compile(
                r'### [^\n]+\n'
                r'(?:(?!###\s|##\s|---).)*?'
                rf'(?:\[([^\]]*)\]\({escaped}\)|{escaped})'
                r'(?:(?!###\s|##\s|---).)*',
                re.DOTALL,
            )
            result = topic_pattern.sub('', result)

        result = re.sub(r'\n{3,}', '\n\n', result)

        # トピック除去後に残った孤立した --- セパレータを除去する
        # 連続する --- を1つに集約する
        result = re.sub(r'(\n---\n)(\n*---\n)+', r'\1', result)
        # セクションヘッダー（## ...）の直後にある --- を除去する
        result = re.sub(r'(## [^\n]+\n)\n*---\n', r'\1\n', result)
        # セクションヘッダー（## ...）の直前または末尾にある --- を除去する
        result = re.sub(r'\n---\n\n*(## |\Z)', r'\n\n\1', result)
        # 最終的な余分な空行を整理する
        result = re.sub(r'\n{3,}', '\n\n', result)

    removed = len(unfixable_urls)
    replaced = len(replacement_urls)
    print(f"  リンク検証完了: 代替リンク={replaced} 件, トピック除去={removed} 件")
    return result


def _regenerate_empty_sections(
    article: str,
    section_definitions: list[dict],
    section_data_map: dict,
    extended_since: datetime,
    llm_clients: list[tuple],
) -> str:
    """リンク除去により空になったセクション（トピックなし）を再取得・再生成する。

    各セクションをチェックし、### 見出しが 0 件のセクションに対して以下を順に試みる:
      1. 拡張時間窓（24h）でカテゴリ専用フィードを再取得して LLM 再生成
      2. 汎用 IT ニュースフィードで LLM 再生成
      3. それでも情報が得られない場合は「情報なし」メッセージを記載する
    """
    for section_def in section_definitions:
        key = section_def["key"]
        header = section_def["header"]
        escaped_header = re.escape(header)

        # セクション本文を抽出してトピック数を確認
        m = re.search(rf'{escaped_header}(.*?)(?=\n## |\Z)', article, re.DOTALL)
        if not m:
            continue

        section_body = m.group(1)
        if re.search(r'^### ', section_body, re.MULTILINE):
            # トピックが存在する → 再生成不要
            continue

        # 「情報なし」メッセージが既に記載されている場合は再処理しない
        if "現在の対象期間に該当する情報はありません。" in section_body:
            continue

        print(f"  [{key}] セクションにトピックがありません。時間窓を延長して再取得します...")

        # 元データの URL を記録し、重複を除いた新規記事のみを使う
        original_urls = {item.get("url", "") for item in section_data_map.get(key, [])}
        extended_data = fetch_category(key, extended_since)
        new_items = [item for item in extended_data if item.get("url", "") not in original_urls]

        # カテゴリ専用フィードに新規データがなければ汎用ニュースにフォールバック
        if not new_items:
            print(f"  [{key}] 専用フィードに新しいデータなし。汎用ニュースにフォールバックします...")
            new_items = fetch_general_news(extended_since, exclude_urls=original_urls)

        if not new_items:
            print(f"  [{key}] 汎用ニュースにも新しいデータがありませんでした。情報なしメッセージを記載します。")
            no_info_section = f"{header}\n\n現在の対象期間に該当する情報はありません。"
            article = re.sub(
                rf'{escaped_header}.*?(?=\n## |\Z)',
                no_info_section.rstrip(),
                article,
                count=1,
                flags=re.DOTALL,
            )
            continue

        print(f"  [{key}] 使用データ: {len(new_items)} 件。セクションを再生成します...")

        new_section = None
        for client, model in llm_clients:
            try:
                new_section = generate_section(client, model, section_def, new_items)
                break
            except OpenAIError as e:
                print(f"  [{key}] 再生成失敗 ({model}): {e}")

        if new_section is None:
            print(f"  [{key}] 全モデルで再生成に失敗しました。情報なしメッセージを記載します。")
            no_info_section = f"{header}\n\n現在の対象期間に該当する情報はありません。"
            article = re.sub(
                rf'{escaped_header}.*?(?=\n## |\Z)',
                no_info_section.rstrip(),
                article,
                count=1,
                flags=re.DOTALL,
            )
            continue

        # 新しいセクションのリンクも検証
        new_section = validate_links(new_section)

        # 再生成後もトピックが0件なら「情報なし」メッセージを記載する
        if not re.search(r'^### ', new_section, re.MULTILINE):
            print(f"  [{key}] 再生成後もトピックがありません。情報なしメッセージを記載します。")
            new_section = f"{header}\n\n現在の対象期間に該当する情報はありません。"

        # 記事内の空セクションを新セクションで置換
        article = re.sub(
            rf'{escaped_header}.*?(?=\n## |\Z)',
            new_section.rstrip(),
            article,
            count=1,
            flags=re.DOTALL,
        )
        print(f"  [{key}] セクション再生成完了")

    return article


# --- フィード取得 -----------------------------------------------------------------


def _fetch_feed(url: str, since: datetime, max_items: int = 5) -> list[dict]:
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    articles = []
    for entry in feed.entries:
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
    if len(all_articles) > MAX_ARTICLES_PER_CATEGORY:
        print(f"  ※ {len(all_articles)} 件 → {MAX_ARTICLES_PER_CATEGORY} 件に制限")
        all_articles = all_articles[:MAX_ARTICLES_PER_CATEGORY]
    return all_articles


def fetch_general_news(since: datetime, exclude_urls: set[str] | None = None) -> list[dict]:
    """汎用 IT ニュースフィードから記事を取得し、指定 URL を除いて返す。"""
    exclude_urls = exclude_urls or set()
    all_articles = []
    for source in GENERAL_NEWS_FEEDS:
        try:
            items = _fetch_feed(source["url"], since)
            for item in items:
                item["source"] = source["name"]
            all_articles.extend(items)
            print(f"    {source['name']}: {len(items)} 件")
        except Exception as e:
            print(f"    {source['name']}: 取得失敗 ({e})")
    new_items = [item for item in all_articles if item.get("url", "") not in exclude_urls]
    if len(new_items) > MAX_ARTICLES_PER_CATEGORY:
        print(f"  ※ 汎用ニュース {len(new_items)} 件 → {MAX_ARTICLES_PER_CATEGORY} 件に制限")
        new_items = new_items[:MAX_ARTICLES_PER_CATEGORY]
    return new_items


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
        "key": "microsoft",
        "header": "## 1. Microsoft",
        "system": (
            "あなたは Microsoft 関連のテクニカルライターです。"
            "SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の Microsoft 関連ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 1. Microsoft」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: URL\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "Microsoft 関連",
    },
    {
        "key": "ai",
        "header": "## 2. AI",
        "system": (
            "あなたは AI・機械学習分野のテクニカルライターです。"
            "SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の AI 関連ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 2. AI」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: URL\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "AI 関連",
    },
    {
        "key": "azure",
        "header": "## 3. Azure",
        "system": (
            "あなたは Microsoft Azure の専門テクニカルライターです。"
            "SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の Azure 関連ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 3. Azure」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: URL\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "Azure 関連",
    },
    {
        "key": "cloud",
        "header": "## 4. クラウド（AWS / GCP / OCI）",
        "system": (
            "あなたはクラウドサービス（AWS・GCP・OCI等）のテクニカルライターです。"
            "SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下のクラウド関連ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "Azure 以外のクラウドサービス（AWS、GCP、OCI 等）のトレンドを対象にしてください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 4. クラウド（AWS / GCP / OCI）」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: URL\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "クラウド（AWS / GCP / OCI）関連",
    },
    {
        "key": "security",
        "header": "## 5. セキュリティ",
        "system": (
            "あなたはサイバーセキュリティのテクニカルライターです。"
            "SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下のセキュリティ関連ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 5. セキュリティ」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: URL\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "セキュリティ関連",
    },
    {
        "key": "itops",
        "header": "## 6. IT運用・管理",
        "system": (
            "あなたは IT 運用・管理の専門テクニカルライターです。"
            "SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の IT 運用・管理ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "**AIOps**（AIを活用したIT運用自動化・異常検知・予測分析）および"
            "**SRE Agent**（AI駆動のサイト信頼性エンジニアリングエージェント）を重点的に取り上げてください。"
            "Microsoft Azure Monitor・System Center 等の Microsoft 製品による AIOps も優先的に含めてください。"
            "ITSM・DevOps・エンドポイント管理・MSP・オブザーバビリティなど IT 運用全般のトレンドも含めてください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 6. IT運用・管理」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: URL\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "IT運用・管理（AIOps / ITSM / DevOps / エンドポイント管理）",
    },
]

# セクションごとの入力文字数上限
SECTION_MAX_INPUT_CHARS = {
    "microsoft": 20_000,
    "ai": 20_000,
    "azure": 20_000,
    "cloud": 20_000,
    "security": 20_000,
    "itops": 20_000,
}

# セクションごとの出力トークン上限
SECTION_MAX_OUTPUT_TOKENS = 3000


def _build_section_prompt(section_def: dict, data: list[dict]) -> str:
    """セクション固有のユーザープロンプトを組み立てる。"""
    label = section_def.get("data_label") or "データ"
    return "\n".join([
        section_def["instruction"],
        "",
        f"### {label}",
        json.dumps(data, ensure_ascii=False, indent=2),
        "",
    ])


def generate_section(
    client,
    model: str,
    section_def: dict,
    data: list[dict],
) -> str:
    """1 セクション分の記事を LLM で生成する。"""
    key = section_def["key"]
    max_input = SECTION_MAX_INPUT_CHARS.get(key, 20_000)

    # データが空リストの場合は LLM を呼ばずに「ありません」を返す
    if len(data) == 0:
        header = section_def.get("header", "")
        return f"{header}\n\n現在の対象期間に該当する情報はありません。"

    user_prompt = _build_section_prompt(section_def, data)
    while len(user_prompt) > max_input:
        if len(data) > 3:
            data.pop()
            user_prompt = _build_section_prompt(section_def, data)
        else:
            break

    # リスト削減後もまだ上限を超える場合はプロンプトを文字数で切り詰める
    if len(user_prompt) > max_input:
        user_prompt = user_prompt[:max_input]

    print(f"    入力: 約 {len(user_prompt):,} 文字")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": section_def["system"]},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=SECTION_MAX_OUTPUT_TOKENS,
    )
    return response.choices[0].message.content.strip()


def generate_article(
    client,
    model: str,
    target_date: str,
    slot: str,
    microsoft_news: list[dict],
    ai_news: list[dict],
    azure_news: list[dict],
    security_news: list[dict],
    cloud_news: list[dict],
    itops_news: list[dict],
) -> str:
    """各セクションを個別の LLM 呼び出しで生成し、1 つの記事に組み立てる。

    セクションごとに独立した API コールを行うことで、各セクションが
    トークン上限を最大限に活用できるようにする。
    """
    formatted_date = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:]}"
    slot_label = "午前" if slot == "am" else "午後"

    section_data_map: dict[str, list[dict]] = {
        "microsoft": microsoft_news,
        "ai": ai_news,
        "azure": azure_news,
        "cloud": cloud_news,
        "security": security_news,
        "itops": itops_news,
    }

    article_parts = [f"# {formatted_date} テクニカル雑談（{slot_label}）"]

    for section_def in SECTION_DEFINITIONS:
        key = section_def["key"]
        data = section_data_map[key]
        print(f"  [{key}] セクション生成中...")
        section_text = generate_section(client, model, section_def, data)
        article_parts.append(section_text)

    return "\n\n".join(article_parts)


# --- メイン処理 -----------------------------------------------------------------


def main():
    if len(sys.argv) < 3:
        print("Usage: python generate_smallchat.py YYYYMMDD am|pm")
        sys.exit(1)

    target_date = sys.argv[1]
    slot = sys.argv[2]  # "am" or "pm"

    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    # 直近12時間の記事を対象
    since = target_dt - timedelta(hours=12)

    print(f"対象日: {target_date} ({slot})")
    print(f"収集期間: {since.isoformat()} 以降")
    print("ニュースを取得中...")

    print("\n[Microsoft]")
    microsoft_news = fetch_category("microsoft", since)
    print(f"  → 合計: {len(microsoft_news)} 件")

    print("\n[AI]")
    ai_news = fetch_category("ai", since)
    print(f"  → 合計: {len(ai_news)} 件")

    print("\n[Azure]")
    azure_news = fetch_category("azure", since)
    print(f"  → 合計: {len(azure_news)} 件")

    print("\n[クラウド]")
    cloud_news = fetch_category("cloud", since)
    print(f"  → 合計: {len(cloud_news)} 件")

    print("\n[セキュリティ]")
    security_news = fetch_category("security", since)
    print(f"  → 合計: {len(security_news)} 件")

    print("\n[IT運用・管理]")
    itops_news = fetch_category("itops", since)
    print(f"  → 合計: {len(itops_news)} 件")

    # 後でリトライ時に重複除外するためセクションキー → 元データのマッピングを保持
    section_data_map = {
        "microsoft": microsoft_news,
        "ai": ai_news,
        "azure": azure_news,
        "cloud": cloud_news,
        "security": security_news,
        "itops": itops_news,
    }

    print("\n記事を生成中（セクションごとに個別生成）...")
    llm_clients = create_llm_clients()
    article = None
    last_error = None
    for client, model in llm_clients:
        try:
            print(f"  モデル: {model}")
            article = generate_article(
                client, model, target_date, slot, microsoft_news, ai_news, azure_news, security_news, cloud_news, itops_news
            )
            break
        except OpenAIError as e:
            print(f"  ⚠ {model} での生成に失敗しました ({e})")
            last_error = e
    if article is None:
        raise RuntimeError(f"全ての LLM プロバイダーで生成に失敗しました。最後のエラー: {last_error}")

    print("\nリンクを検証中...")
    article = validate_links(article)

    # リンク除去で空になったセクションを時間窓を広げて再生成する
    print("\n空セクションの確認...")
    extended_since = target_dt - timedelta(hours=24)
    article = _regenerate_empty_sections(
        article, SECTION_DEFINITIONS, section_data_map, extended_since, llm_clients
    )

    output_dir = "smallchat"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date}_{slot}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
