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
        {"name": "Microsoft Japan Blog", "url": "https://news.microsoft.com/ja-jp/feed/"},
        {"name": "Google Japan Blog", "url": "https://japan.googleblog.com/feeds/posts/default?alt=rss"},
        {"name": "Cybozu Inside Out", "url": "https://blog.cybozu.io/feed"},
        {"name": "Mercari Engineering Blog", "url": "https://engineering.mercari.com/blog/feed.xml"},
        {"name": "LINE Engineering Blog", "url": "https://engineering.linecorp.com/ja/feed.xml"},
        {"name": "ZOZO Tech Blog", "url": "https://techblog.zozo.com/feed"},
        {"name": "Recruit Tech Blog", "url": "https://techblog.recruit.co.jp/feed"},
        {"name": "DeNA Engineering Blog", "url": "https://engineering.dena.com/blog/index.xml"},
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
        {"name": "Google Blog", "url": "https://blog.google/rss/"},
        {"name": "Microsoft Blog", "url": "https://blogs.microsoft.com/feed/"},
        {"name": "Google Developers Blog", "url": "https://developers.googleblog.com/feeds/posts/default?alt=rss"},
        {"name": "Google Cloud Blog", "url": "https://cloud.google.com/feeds/gcp-blog-atom.xml"},
        {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"},
        {"name": "Google News - Wiz", "url": "https://news.google.com/rss/search?q=wiz.io+security+cloud&hl=en&gl=US&ceid=US:en"},
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
        {"name": "X(旧Twitter) テック話題 JP", "url": "https://news.google.com/rss/search?q=X+%E6%97%A7Twitter+%E3%83%86%E3%83%83%E3%82%AF+%E3%82%A8%E3%83%B3%E3%82%B8%E3%83%8B%E3%82%A2&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "X(旧Twitter) 新機能・ニュース JP", "url": "https://news.google.com/rss/search?q=X+%E6%97%A7Twitter+%E6%96%B0%E6%A9%9F%E8%83%BD+%E3%82%A2%E3%83%83%E3%83%97%E3%83%87%E3%83%BC%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "X (formerly Twitter) Tech EN", "url": "https://news.google.com/rss/search?q=X+formerly+Twitter+tech+developer&hl=en&gl=US&ceid=US:en"},
        {"name": "Reddit DevOps", "url": "https://www.reddit.com/r/devops/.rss"},
        {"name": "Reddit SysAdmin", "url": "https://www.reddit.com/r/sysadmin/.rss"},
        {"name": "Qiita トレンド", "url": "https://qiita.com/popular-items/feed"},
        {"name": "Reddit Artificial Intelligence", "url": "https://www.reddit.com/r/artificial/.rss"},
        {"name": "Reddit Cloud Computing", "url": "https://www.reddit.com/r/cloudcomputing/.rss"},
    ],
    # --- コミュニティイベント参加レポ・イベント宣伝 ---
    "event_reports": [
        {"name": "Google News connpass 参加レポ", "url": "https://news.google.com/rss/search?q=connpass+%E5%8F%82%E5%8A%A0+%E3%83%AC%E3%83%9D+%E6%9D%B1%E4%BA%AC+%E7%A5%9E%E5%A5%88%E5%B7%9D&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News 勉強会 参加レポ 東京", "url": "https://news.google.com/rss/search?q=%E5%8B%89%E5%BC%B7%E4%BC%9A+%E5%8F%82%E5%8A%A0%E3%83%AC%E3%83%9D+%E6%9D%B1%E4%BA%AC&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Zenn connpass イベント", "url": "https://zenn.dev/api/rss_feed/topic/connpass"},
        {"name": "Zenn 勉強会", "url": "https://zenn.dev/api/rss_feed/topic/勉強会"},
        {"name": "Zenn LT イベント", "url": "https://zenn.dev/api/rss_feed/topic/lt"},
        {"name": "Qiita connpass", "url": "https://qiita.com/tags/connpass/feed"},
        {"name": "Qiita 勉強会", "url": "https://qiita.com/tags/勉強会/feed"},
        {"name": "Qiita イベント", "url": "https://qiita.com/tags/イベント/feed"},
        {"name": "はてなブックマーク 勉強会", "url": "https://b.hatena.ne.jp/q/%E5%8B%89%E5%BC%B7%E4%BC%9A%20%E5%8F%82%E5%8A%A0%E3%83%AC%E3%83%9D?mode=rss&sort=hot"},
        {"name": "Google News note イベント宣伝", "url": "https://news.google.com/rss/search?q=site%3Anote.com+connpass+OR+%E5%8B%89%E5%BC%B7%E4%BC%9A+OR+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Zenn 勉強会イベント", "url": "https://news.google.com/rss/search?q=site%3Azenn.dev+%E5%8B%89%E5%BC%B7%E4%BC%9A+OR+connpass+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
    ],
}

HTTP_HEADERS = {
    "User-Agent": "daily-updates-bot/1.0 (GitHub Actions; +https://github.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
}

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


def _format_bare_reference_links(markdown: str) -> str:
    """**参考リンク**: の後に裸の URL または URL をラベルにしたリンクがある場合、
    直近の ### 見出しをラベルにしたハイパーリンクへ変換する。"""
    lines = markdown.splitlines()
    current_heading = ""
    result = []
    for line in lines:
        heading_match = re.match(r'^###\s+(.+)', line)
        if heading_match:
            current_heading = heading_match.group(1).strip()

        # 裸の URL: **参考リンク**: https://...
        ref_bare = re.match(r'^(\*\*参考リンク\*\*:\s*)(https?://\S+)\s*$', line)
        # URL をラベルにしたリンク: **参考リンク**: [https://...](https://...)
        ref_url_label = re.match(
            r'^(\*\*参考リンク\*\*:\s*)\[(https?://[^\]]+)\]\((https?://[^)]+)\)\s*$', line
        )
        if ref_bare:
            prefix = ref_bare.group(1)
            url = ref_bare.group(2)
            label = current_heading if current_heading else url
            line = f"{prefix}[{label}]({url})"
        elif ref_url_label:
            prefix = ref_url_label.group(1)
            url = ref_url_label.group(3)
            label = current_heading if current_heading else url
            line = f"{prefix}[{label}]({url})"

        result.append(line)
    return "\n".join(result)


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


# セクションキー → フィードサブキーのマッピング（_fetch_section_category / _regenerate_empty_sections で使用）
SECTION_FEED_KEYS: dict[str, list[str]] = {
    "azure": ["azure"],
    "tech": ["tech_ja", "tech_en"],
    "sns": ["sns"],
    "business": ["business_ja", "business_en"],
}


def _fetch_section_category(key: str, since: datetime) -> list[dict]:
    """セクションキーに対応するフィードカテゴリから記事を取得する。"""
    sub_keys = SECTION_FEED_KEYS.get(key, [key])
    all_items = []
    for sub_key in sub_keys:
        all_items.extend(fetch_category(sub_key, since))
    return all_items


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

        # dict 型データのセクション（community など）はスキップ
        original_data = section_data_map.get(key, [])
        if isinstance(original_data, dict):
            continue

        print(f"  [{key}] セクションにトピックがありません。時間窓を延長して再取得します...")

        # 元データの URL を記録し、重複を除いた新規記事のみを使う
        original_urls = {item.get("url", "") for item in original_data}
        extended_data = _fetch_section_category(key, extended_since)
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
                new_section = generate_section(client, model, section_def, new_items, since=extended_since)
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
        new_section = _format_bare_reference_links(new_section)
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

        if not pub_date or pub_date < since:
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

    # URL 重複排除（異なるフィードが同じ記事を参照する場合）
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for item in all_articles:
        url = item.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)

    # 公開日時の降順でソート（新しい記事が先頭、日時なしは末尾）
    deduped.sort(key=lambda x: x.get("datePublished", "") or "", reverse=True)

    return deduped


def fetch_general_news(since: datetime, exclude_urls: set[str] | None = None) -> list[dict]:
    """汎用 IT ニュースフィードから記事を収集する（フォールバック用）。

    exclude_urls が指定された場合、その URL を持つ記事は除外する（重複排除用）。
    """
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
    new_items = [a for a in all_articles if a.get("url", "") not in (exclude_urls or set())]
    # 公開日時の降順でソート（新しい記事が先頭、日時なしは末尾）して上位 20 件に制限
    new_items.sort(key=lambda x: x.get("datePublished", "") or "", reverse=True)
    if len(new_items) > 20:
        print(f"  ※ 汎用ニュース {len(new_items)} 件 → 20 件に制限")
        new_items = new_items[:20]
    return new_items


CONNPASS_API_URL = "https://connpass.com/api/v2/events/"
CONNPASS_RSS_URL = "https://connpass.com/search/"
# v2 API では prefecture パラメータが廃止されたため keyword で都道府県名を検索する
CONNPASS_TARGET_PREFECTURES = ["東京都", "神奈川県"]
# 取得する最大イベント数
CONNPASS_MAX_EVENTS = 20
# 先読み日数（今日から何日先まで）
CONNPASS_LOOKAHEAD_DAYS = 60


def _fetch_connpass_events_rss(target_date: str) -> list[dict]:
    """connpass RSS フィードを使用してイベントを取得する（API キー不要）。

    RSS で取得できる情報はイベントタイトル・URL・概要のみです。
    開催日時・定員・場所などの詳細情報は取得できません。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)

    events = []
    seen_urls: set[str] = set()

    # 今月と翌月のイベントを検索する
    search_months = sorted({
        target_dt.strftime("%Y%m"),
        (target_dt + timedelta(days=30)).strftime("%Y%m"),
    })

    for pref in CONNPASS_TARGET_PREFECTURES:
        for ym in search_months:
            params = {
                "format": "rss",
                "keyword": pref,
                "ym": ym,
            }
            try:
                resp = requests.get(
                    CONNPASS_RSS_URL,
                    params=params,
                    headers=HTTP_HEADERS,
                    timeout=30,
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
                count = 0
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    title = entry.get("title", "").strip()
                    description = entry.get("summary", "").strip()
                    events.append({
                        "title": title,
                        "catch": description[:200] if description else "",
                        "event_url": url,
                        "started_at": "",
                        "place": "",
                        "address": "",
                        "accepted": 0,
                        "limit": 0,
                        "series": "",
                    })
                    count += 1
                print(f"    connpass RSS ({pref} {ym}): {count} 件取得")
            except Exception as e:
                print(f"    connpass RSS ({pref} {ym}): 取得失敗 ({e})")

    if len(events) > CONNPASS_MAX_EVENTS:
        print(f"  ※ connpass RSS {len(events)} 件 → {CONNPASS_MAX_EVENTS} 件に制限")
        events = events[:CONNPASS_MAX_EVENTS]

    return events


def fetch_connpass_events(target_date: str) -> list[dict]:
    """connpassから東京・神奈川の近日開催コミュニティイベントを取得する。

    CONNPASS_API_KEY 環境変数が設定されている場合は API v2 を使用し、
    未設定の場合は RSS フィード（API キー不要）にフォールバックする。
    RSS フォールバック時は開催日時・定員・場所などの詳細情報は取得できない。
    """
    api_key = os.environ.get("CONNPASS_API_KEY", "")
    if not api_key:
        print("    connpass: CONNPASS_API_KEY が未設定のため RSS フィードで取得します")
        return _fetch_connpass_events_rss(target_date)

    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    cutoff_dt = target_dt + timedelta(days=CONNPASS_LOOKAHEAD_DAYS)

    # (event_dt, event_dict) のリストで収集し、後でdatetimeでソートする
    events_with_dt: list[tuple] = []
    seen_ids: set[int] = set()

    for pref in CONNPASS_TARGET_PREFECTURES:
        params = {
            "keyword": pref,
            "count": CONNPASS_MAX_EVENTS,
            "order": 2,  # 開催日順
        }
        connpass_headers = {
            **HTTP_HEADERS,
            "Accept": "application/json",
            "X-API-Key": api_key,
        }
        try:
            resp = requests.get(
                CONNPASS_API_URL,
                params=params,
                headers=connpass_headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            print(f"    connpass ({pref}): {data.get('results_returned', 0)} 件取得")

            for event in data.get("events", []):
                event_id = event.get("id")
                # 重複排除（複数都道府県で同じイベントが出る場合）
                if event_id and event_id in seen_ids:
                    continue
                if event_id:
                    seen_ids.add(event_id)

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

                # v2 API では event_url フィールドが url に変更された
                event_url = event.get("url") or event.get("event_url", "")

                events_with_dt.append((event_dt, {
                    "title": event.get("title", "").strip(),
                    "catch": event.get("catch", "").strip(),
                    "event_url": event_url,
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
        "header": "## 1. Azure アップデート情報",
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
        "header": "## 2. ニュースで話題のテーマ",
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
        "header": "## 3. SNSで話題のテーマ",
        "system": (
            "あなたは SNS・トレンドニュースの専門ライターです。"
            "提供されたニュースを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の SNS・トレンド情報（はてブ・Reddit・X 等）から 5〜6 個のトピックを選定し、"
            "マークダウン形式で出力してください。\n"
            "X（旧Twitter）で話題になっている IT・テクノロジー関連トピックを優先的に含めてください。\n"
            "先頭に「## 3. SNSで話題のテーマ」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "SNS / トレンド（はてブ・Reddit・X）",
    },
    {
        "key": "business",
        "header": "## 4. ビジネスホットトピック",
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
        "key": "community",
        "header": "## 5. コミュニティイベント情報（東京・神奈川）",
        "system": (
            "あなたはコミュニティイベント情報の専門ライターです。"
            "提供されたデータを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の connpass イベントデータと参加レポート・イベント宣伝記事を元に"
            "「## 5. コミュニティイベント情報（東京・神奈川）」セクションを作成してください。\n\n"
            "先頭に「## 5. コミュニティイベント情報（東京・神奈川）」を出力し、"
            "以下の 2 サブセクション構成で出力してください。\n\n"
            "### 📅 申し込み受付中のイベント\n\n"
            "connpass イベントデータから申し込み可能な近日開催イベントを箇条書きで列挙してください。"
            "各イベントに「イベント名（リンク付き）」「開催日時」「場所」「概要」"
            "「参加状況（申込数/定員）」を記載してください。"
            "イベントデータが空の場合は「現在取得できるイベント情報はありません」と記載してください。\n\n"
            "### 📝 参加レポート・イベント宣伝まとめ\n\n"
            "参加レポートデータには Zenn・Qiita・note・はてなブックマーク などで公開された"
            "勉強会・コミュニティイベントの参加レポート、開催レポート、イベント告知記事が含まれます。"
            "これらをまとめ、各記事は見出し・要約・参考リンクで構成してください。"
            "レポートが少ない場合は取得できた範囲で記載してください。\n\n"
            "コードブロックで囲まないこと。"
        ),
        # community セクションは複数のデータソースを持つため data_label は使用しない
        "data_label": None,
    },
]

# セクションごとの入力文字数上限
SECTION_MAX_INPUT_CHARS = {
    "azure": 30_000,
    "tech": 40_000,
    "business": 40_000,
    "sns": 30_000,
    "community": 20_000,
}

# セクションごとの出力トークン上限
SECTION_MAX_OUTPUT_TOKENS = 4096


def _build_section_prompt(section_def: dict, data: dict | list, since: datetime | None = None) -> str:
    """セクション固有のユーザープロンプトを組み立てる。

    data が dict の場合は {ラベル: ペイロード} の形式、
    list の場合は section_def["data_label"] を使ってラベルを付ける。
    since が指定された場合、LLM に対象期間の注意事項を付記する。
    """
    lines = []
    if since is not None:
        since_jst = since.astimezone(JST)
        date_notice = (
            f"【対象期間】{since_jst.strftime('%Y年%m月%d日 %H:%M')} (JST) 以降に公開された記事のみを対象としてください。\n"
            "古い記事（対象期間より前に公開されたもの）は含めないでください。\n"
            "もし取り上げる話題が以前の記事へのアップデートである場合は、"
            "そのアップデートであることがわかるよう更新の経緯を明記し、元記事や関連リンクを記載してください。"
        )
        lines.append(date_notice)
        lines.append("")
    lines.append(section_def["instruction"])
    lines.append("")
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
    since: "datetime | None" = None,
) -> str:
    """1 セクション分の記事を LLM で生成する。"""
    key = section_def["key"]
    max_input = SECTION_MAX_INPUT_CHARS.get(key, 30_000)

    # データが空リストの場合は LLM を呼ばずに「ありません」を返す
    if isinstance(data, list) and len(data) == 0:
        header = section_def.get("header", "")
        return f"{header}\n\n現在の対象期間に該当する情報はありません。"

    # 入力が大きすぎる場合はリストを末尾から削減する
    if isinstance(data, dict):
        all_lists = [v for v in data.values() if isinstance(v, list)]
    else:
        all_lists = [data] if isinstance(data, list) else []

    user_prompt = _build_section_prompt(section_def, data, since=since)
    while len(user_prompt) > max_input:
        trimmed = False
        for lst in all_lists:
            if len(lst) > 3:
                lst.pop()
                trimmed = True
        if not trimmed:
            break
        user_prompt = _build_section_prompt(section_def, data, since=since)

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
    connpass_events: list[dict],
    event_reports: list[dict],
    since: "datetime | None" = None,
) -> str:
    """各セクションを個別の LLM 呼び出しで生成し、1 つの記事に組み立てる。

    セクションごとに独立した API コールを行うことで、各セクションが
    トークン上限を最大限に活用できるようにする。
    since が指定された場合、各セクションに対象期間の注意事項を付記する。
    """
    formatted_date = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:]}"

    section_data_map: dict[str, dict | list] = {
        "azure": azure_news,
        "tech": tech_news,
        "sns": sns_news,
        "business": business_news,
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
        section_text = generate_section(client, model, section_def, data, since=since)
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
                client, model, target_date, azure_news, tech_news, business_news, sns_news,
                connpass_events, event_reports, since=since,
            )
            break
        except OpenAIError as e:
            print(f"  ⚠ {model} での生成に失敗しました ({e})")
            last_error = e
    if article is None:
        raise RuntimeError(f"全ての LLM プロバイダーで生成に失敗しました。最後のエラー: {last_error}")

    print("\nリンクを検証中...")
    article = _format_bare_reference_links(article)
    article = validate_links(article)

    # リンク除去で空になったセクションを時間窓を広げて再生成する
    print("\n空セクションの確認...")
    section_data_map = {
        "azure": azure_news,
        "tech": tech_news,
        "sns": sns_news,
        "business": business_news,
        "community": {
            "connpass イベント（東京・神奈川、申し込み受付中）": connpass_events,
            "コミュニティイベント参加レポート": event_reports,
        },
    }
    extended_since = target_dt - timedelta(hours=24)
    article = _regenerate_empty_sections(
        article, SECTION_DEFINITIONS, section_data_map, extended_since, llm_clients
    )

    output_dir = "updates"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
