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
        {"name": "Netflix Tech Blog", "url": "https://netflixtechblog.com/feed"},
        {"name": "Uber Engineering Blog", "url": "https://eng.uber.com/feed/"},
        {"name": "Meta Engineering Blog", "url": "https://engineering.fb.com/feed/"},
        {"name": "GitHub Blog", "url": "https://github.blog/feed/"},
        {"name": "Stripe Engineering Blog", "url": "https://stripe.com/blog/engineering.rss"},
        {"name": "Airbnb Engineering Blog", "url": "https://medium.com/airbnb-engineering/feed"},
        {"name": "Discord Engineering Blog", "url": "https://discord.com/category/engineering/rss"},
        {"name": "InfoQ", "url": "https://feed.infoq.com/"},
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
        {"name": "Google News connpass IT 参加レポ", "url": "https://news.google.com/rss/search?q=connpass+IT+%E5%8B%89%E5%BC%B7%E4%BC%9A+%E5%8F%82%E5%8A%A0%E3%83%AC%E3%83%9D&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Azure User Group", "url": "https://news.google.com/rss/search?q=Azure+User+Group+%E5%8B%89%E5%BC%B7%E4%BC%9A+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News AWS JAWS 勉強会", "url": "https://news.google.com/rss/search?q=JAWS+AWS+%E5%8B%89%E5%BC%B7%E4%BC%9A+connpass&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News クラウド DevOps IT 勉強会", "url": "https://news.google.com/rss/search?q=%E3%82%AF%E3%83%A9%E3%82%A6%E3%83%89+DevOps+%E5%8B%89%E5%BC%B7%E4%BC%9A+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News AIOps FinOps コミュニティ", "url": "https://news.google.com/rss/search?q=AIOps+OR+FinOps+OR+MLOps+%E3%82%B3%E3%83%9F%E3%83%A5%E3%83%8B%E3%83%86%E3%82%A3+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Zenn connpass イベント", "url": "https://zenn.dev/api/rss_feed/topic/connpass"},
        {"name": "Zenn 勉強会", "url": "https://zenn.dev/api/rss_feed/topic/勉強会"},
        {"name": "Zenn LT イベント", "url": "https://zenn.dev/api/rss_feed/topic/lt"},
        {"name": "Qiita connpass", "url": "https://qiita.com/tags/connpass/feed"},
        {"name": "Qiita 勉強会", "url": "https://qiita.com/tags/勉強会/feed"},
        {"name": "はてなブックマーク IT 勉強会", "url": "https://b.hatena.ne.jp/q/IT%20%E5%8B%89%E5%BC%B7%E4%BC%9A%20%E5%8F%82%E5%8A%A0%E3%83%AC%E3%83%9D?mode=rss&sort=hot"},
        {"name": "Google News Zenn IT 勉強会イベント", "url": "https://news.google.com/rss/search?q=site%3Azenn.dev+%E5%8B%89%E5%BC%B7%E4%BC%9A+%E3%82%A8%E3%83%B3%E3%82%B8%E3%83%8B%E3%82%A2+connpass&hl=ja&gl=JP&ceid=JP:ja"},
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

# マークダウンリンクのラベル部分に対応する正規表現フラグメント。
# [In preview] のような角括弧を含むラベルも 1 段階までサポートする。
# 例: [[In preview] Public Preview: Event Grid](https://...)
_LINK_LABEL_RE = r'[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*'


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
    link_pattern = re.compile(rf'\[({_LINK_LABEL_RE})\]\((https?://[^)]+)\)')
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
                rf'(?:\[(?:{_LINK_LABEL_RE})\]\({escaped}\)|{escaped})'  # 無効 URL を含む行
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


# --- コンテンツ検証 -------------------------------------------------------------


def verify_content(markdown: str) -> str:
    """生成されたマークダウンの形式とリンク整合性を検証・修正する。

    生成やリンク検証とは独立した検証プロセスとして、以下の項目をチェックする:
      1. 見出し（###）がハイパーリンク化されていないこと
      2. 各トピックに **要約** と **参考リンク** が含まれること
      3. **参考リンク** が [タイトル](URL) 形式であること
      4. セクション末尾に不要な締め文がないこと
      5. 連続 --- セパレータや孤立セパレータがないこと
    修正可能な問題は自動修正し、全ての検出事項をログ出力する。
    """
    lines = markdown.split('\n')
    fixed_lines: list[str] = []
    issues: list[str] = []

    # --- 1. 見出しのハイパーリンク解除 ---
    _heading_link_re = re.compile(
        r'^(###\s+)\[(' + _LINK_LABEL_RE + r')\]\(https?://[^)]+\)\s*$'
    )
    for line in lines:
        m = _heading_link_re.match(line)
        if m:
            label = m.group(2).strip()
            fixed_line = f"{m.group(1)}{label}"
            fixed_lines.append(fixed_line)
            issues.append(f"見出しリンク修正: '{label}'")
        else:
            fixed_lines.append(line)

    result = '\n'.join(fixed_lines)

    # --- 2. トピック構造の検証 ---
    # セクション（## で始まる）ごとにトピック（### で始まる）を抽出して検証する
    section_pattern = re.compile(r'^## .+', re.MULTILINE)
    section_starts = [m.start() for m in section_pattern.finditer(result)]

    for i, start in enumerate(section_starts):
        end = section_starts[i + 1] if i + 1 < len(section_starts) else len(result)
        section_text = result[start:end]
        section_header_match = re.match(r'^## (.+)', section_text)
        section_name = section_header_match.group(1).strip() if section_header_match else "不明"

        # 「情報なし」セクションはスキップ
        if "現在の対象期間に該当する情報はありません。" in section_text:
            continue

        # トピック（###）を抽出
        topic_pattern = re.compile(r'^### .+', re.MULTILINE)
        topics = list(topic_pattern.finditer(section_text))

        if not topics:
            issues.append(f"空セクション検出: {section_name}")
            continue

        for j, topic_match in enumerate(topics):
            topic_start = topic_match.start()
            topic_end = topics[j + 1].start() if j + 1 < len(topics) else (end - start)
            topic_block = section_text[topic_start:topic_end]
            topic_title = topic_match.group(0).replace('### ', '').strip()

            # **要約** チェック — コミュニティイベントセクションの箇条書きサブセクションは除外
            is_community_list = (
                "コミュニティ" in section_name
                and (topic_title.startswith("📅") or topic_title.startswith("📝"))
            )
            if not is_community_list and '**要約**' not in topic_block:
                issues.append(f"要約なし: [{section_name}] {topic_title}")

            # **参考リンク** チェック — コミュニティ箇条書きサブセクションは除外
            if not is_community_list and '**参考リンク**' not in topic_block:
                issues.append(f"参考リンクなし: [{section_name}] {topic_title}")
            elif not is_community_list:
                # 参考リンクの形式チェック: [text](URL) が含まれるか
                ref_line_re = re.compile(r'\*\*参考リンク\*\*:\s*(.*)', re.MULTILINE)
                ref_match = ref_line_re.search(topic_block)
                if ref_match:
                    ref_value = ref_match.group(1).strip()
                    link_re = re.compile(rf'\[{_LINK_LABEL_RE}\]\(https?://[^)]+\)')
                    if not link_re.search(ref_value):
                        issues.append(f"参考リンク形式不正: [{section_name}] {topic_title}")

    # --- 3. セクション末尾の締め文検出 ---
    # 最後のトピックの **参考リンク** (または ---) 以降に余分なテキストがないかチェック
    _closing_re = re.compile(
        r'(\*\*参考リンク\*\*:\s*\[' + _LINK_LABEL_RE + r'\]\(https?://[^)]+\))'
        r'(\n\n(?!###\s|##\s|---|\Z).*?)(?=\n(?:###\s|##\s|---)\b|\Z)',
        re.MULTILINE | re.DOTALL,
    )

    def _remove_closing_text(m: re.Match[str]) -> str:
        trailing = m.group(2).strip()
        if trailing and not trailing.startswith('**') and not trailing.startswith('#'):
            issues.append(f"締め文検出: '{trailing[:60]}...'")
            return m.group(1)
        return m.group(0)

    result = _closing_re.sub(_remove_closing_text, result)

    # --- 4. 孤立・連続 --- セパレータの修正 ---
    result = re.sub(r'(\n---\n)(\n*---\n)+', r'\n---\n', result)
    result = re.sub(r'(## [^\n]+\n)\n*---\n', r'\1\n', result)
    result = re.sub(r'\n---\n\n*(## |\Z)', r'\n\n\1', result)
    result = re.sub(r'\n{3,}', '\n\n', result)

    # --- 検証結果のレポート ---
    if issues:
        print(f"  コンテンツ検証: {len(issues)} 件の問題を検出（修正済み含む）")
        for issue in issues:
            print(f"    ⚠ {issue}")
    else:
        print("  コンテンツ検証: 問題なし")

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
# 最終出力に含めるイベント数の上限
CONNPASS_MAX_EVENTS = 20
# API 1 リクエストで取得する最大件数（connpass v2 API の上限は 100）
CONNPASS_API_FETCH_COUNT = 100
# 先読み日数（今日から何日先まで）
CONNPASS_LOOKAHEAD_DAYS = 90

# Google News RSS で X(Twitter) 発のイベント告知を間接的に検索するクエリ群
# X 上でシェアされた IT イベント情報は Google News に反映されることがある
_CONNPASS_SOCIAL_DISCOVERY_QUERIES = [
    "IT 勉強会 東京 connpass 申込",
    "エンジニア イベント 東京 ハンズオン connpass",
    "JAWS AWS 東京 勉強会 開催",
    "Azure クラウド 東京 勉強会 コミュニティ",
    "X Twitter エンジニア 勉強会 東京 開催",
    "Kubernetes Docker Python 東京 勉強会",
    "神奈川 IT コミュニティ 勉強会 申込",
]

# connpass RSS 追加検索の種になる既知 IT コミュニティキーワード
_CONNPASS_COMMUNITY_SEED_KEYWORDS = [
    "JAWS",
    "JAWSUG",
    "GCPUG",
    "CloudNative",
    "Azure User Group",
    "SRE",
    "DevOps",
    "LLM",
    "機械学習",
    "セキュリティ",
    "Python",
    "TypeScript",
    "Kubernetes",
]

# IT 関連イベントを判定するキーワードリスト（タイトルや説明文に含まれるかチェック）
CONNPASS_IT_KEYWORDS = [
    # クラウド・インフラ
    "cloud", "クラウド", "azure", "aws", "gcp", "google cloud",
    "kubernetes", "k8s", "docker", "terraform", "ansible", "iac",
    "serverless", "サーバーレス", "container", "コンテナ",
    # DevOps・SRE・運用
    "devops", "devsecops", "sre", "gitops", "cicd", "ci/cd",
    "mlops", "aiops", "finops", "platform engineering",
    # AI・機械学習
    "llm", "機械学習", "深層学習", "deep learning",
    "chatgpt", "openai", "anthropic", "copilot", "生成ai", "生成AI",
    "langchain", "hugging face",
    # セキュリティ
    "security", "セキュリティ", "siem", "脆弱性", "pentest",
    "zerotrust", "zero trust", "ゼロトラスト",
    # プログラミング言語・フレームワーク
    "python", "javascript", "typescript", "java", "rust",
    "react", "vue", "angular", "django", "rails",
    "マイクロサービス", "microservices",
    # データ・分析
    "データ", "analytics", "アナリティクス", "etl",
    "databricks", "snowflake", "bigquery",
    # IT全般
    "エンジニア", "engineer", "developer", "デベロッパー",
    "プログラミング", "programming", "iot", "5g",
    # コミュニティ・イベント形式
    "勉強会", "ハンズオン", "オープンソース", "open source",
    # コミュニティ・グループ名称
    "jaws", "jawsug", "azure user group", "jug", "gcpug", "jawsdays",
    "microsoft",
    # IT インフラ・その他
    "インフラ", "infra", "database",
    "ブロックチェーン", "blockchain", "web3",
]

# 単語境界マッチが必要な短い英数字キーワード（部分文字列としてヒットしやすいもの）
# 例: "ai" が "painting" にヒットしないよう [a-z0-9] の境界でマッチする
_CONNPASS_IT_KEYWORDS_WORD_BOUNDARY = frozenset({"ai", "ml", "go", "sre", "rag", "soc", "db", "api"})


def _is_it_event(event: dict) -> bool:
    """イベントが IT 関連かどうかを判定する。

    イベントのタイトルまたはキャッチコピーに CONNPASS_IT_KEYWORDS のいずれかが
    含まれる場合に True を返す。
    短い英数字キーワード（_CONNPASS_IT_KEYWORDS_WORD_BOUNDARY）は部分文字列への
    誤ヒットを防ぐため単語境界（[a-z0-9] 非隣接）でマッチする。
    """
    text = (event.get("title", "") + " " + event.get("catch", "")).lower()
    # 通常の部分文字列マッチ
    for kw in CONNPASS_IT_KEYWORDS:
        if kw.lower() in text:
            return True
    # 短い英数字キーワードは誤ヒット防止のため単語境界マッチ
    for kw in _CONNPASS_IT_KEYWORDS_WORD_BOUNDARY:
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text):
            return True
    return False


def _fetch_connpass_events_rss(target_date: str) -> list[dict]:
    """connpass RSS フィードを使用してイベントを取得する（API キー不要）。

    RSS で取得できる情報はイベントタイトル・URL・概要のみです。
    開催日時・定員・場所などの詳細情報は取得できません。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)

    events = []
    seen_urls: set[str] = set()

    # 今月から CONNPASS_LOOKAHEAD_DAYS 日先の月まで、月単位で列挙する
    end_dt = target_dt + timedelta(days=CONNPASS_LOOKAHEAD_DAYS)
    search_months = []
    y, m = target_dt.year, target_dt.month
    while (y, m) <= (end_dt.year, end_dt.month):
        search_months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

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
                    title = entry.get("title", "").strip()
                    description = entry.get("summary", "").strip()
                    event = {
                        "title": title,
                        # 表示用は 200 文字に切り詰め（IT 判定には使わない）
                        "catch": description[:200] if description else "",
                        "event_url": url,
                        "started_at": "",
                        "place": "",
                        "address": "",
                        "accepted": 0,
                        "limit": 0,
                        "series": "",
                    }
                    # IT 判定には切り詰め前の full description を使用する
                    if not _is_it_event({"title": title, "catch": description}):
                        continue
                    seen_urls.add(url)
                    events.append(event)
                    count += 1
                print(f"    connpass RSS ({pref} {ym}): {count} 件取得")
            except Exception as e:
                print(f"    connpass RSS ({pref} {ym}): 取得失敗 ({e})")

    if len(events) > CONNPASS_MAX_EVENTS:
        print(f"  ※ connpass RSS {len(events)} 件 → {CONNPASS_MAX_EVENTS} 件に制限")
        events = events[:CONNPASS_MAX_EVENTS]

    return events


def _discover_event_keywords_from_social() -> list[str]:
    """Google News / X(Twitter) 経由の IT イベント言及からキーワードを収集する（第2段階）。

    X(Twitter) でシェアされたイベント情報は Google News に反映されることがある。
    _CONNPASS_SOCIAL_DISCOVERY_QUERIES で Google News を検索し、記事タイトルや
    概要に登場するコミュニティ名・技術キーワードを抽出して返す。
    既知シードキーワード (_CONNPASS_COMMUNITY_SEED_KEYWORDS) は常に含める。
    """
    gathered: set[str] = set(_CONNPASS_COMMUNITY_SEED_KEYWORDS)

    for query in _CONNPASS_SOCIAL_DISCOVERY_QUERIES:
        feed_url = (
            "https://news.google.com/rss/search?q="
            + quote_plus(query)
            + "&hl=ja&gl=JP&ceid=JP:ja"
        )
        try:
            resp = requests.get(feed_url, headers=HTTP_HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:6]:
                combined = entry.get("title", "") + " " + entry.get("summary", "")
                # 「【イベント名】」「「イベント名」」形式の固有名詞を抽出
                for match in re.finditer(r"[「【]([^」】\n]{3,30})[」】]", combined):
                    candidate = match.group(1).strip()
                    if _is_it_event({"title": candidate, "catch": ""}):
                        gathered.add(candidate)
        except Exception as e:
            print(f"    イベントキーワード収集失敗 ({query[:25]}...): {e}")

    result = sorted(gathered)
    print(f"    SNS/ニュース発掘キーワード: {len(result)} 件")
    return result


def _search_connpass_rss_by_keyword(
    keyword: str,
    search_months: list[str],
    seen_urls: set[str],
) -> list[dict]:
    """指定キーワードで connpass RSS を月別検索して IT イベントを返す（第3段階）。

    seen_urls に登録済みの URL は重複として除外し、新たに追加した URL は
    seen_urls に登録する（呼び出し側との共有セット）。
    """
    events = []
    for ym in search_months:
        params = {"format": "rss", "keyword": keyword, "ym": ym}
        try:
            resp = requests.get(
                CONNPASS_RSS_URL,
                params=params,
                headers=HTTP_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue
                title = entry.get("title", "").strip()
                desc = entry.get("summary", "").strip()
                if not _is_it_event({"title": title, "catch": desc}):
                    continue
                seen_urls.add(url)
                events.append(
                    {
                        "title": title,
                        "catch": desc[:200],
                        "event_url": url,
                        "started_at": "",
                        "place": "",
                        "address": "",
                        "accepted": 0,
                        "limit": 0,
                        "series": "",
                    }
                )
        except Exception:
            pass
    return events


def fetch_connpass_events(target_date: str) -> list[dict]:
    """connpassから東京・神奈川の近日開催コミュニティイベントを取得する（多段検索）。

    API キー不要の多段検索で upcoming IT イベントを発掘する:

    1. connpass RSS 月別検索（東京・神奈川）
    2. Google News / X(Twitter) 言及からコミュニティキーワードを収集
    3. 収集キーワードで connpass RSS を追加検索（直近 3 ヶ月、上位 12 キーワード）
    4. CONNPASS_API_KEY が設定されている場合は v2 API でも補完する

    ステップ 1〜3 は API キー不要のため、CONNPASS_API_KEY が未設定でも動作する。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    end_dt = target_dt + timedelta(days=CONNPASS_LOOKAHEAD_DAYS)

    # 検索月リストを構築（全段階で共用）
    search_months: list[str] = []
    y, m = target_dt.year, target_dt.month
    while (y, m) <= (end_dt.year, end_dt.month):
        search_months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    # --- 段階 1: connpass RSS 月別検索（東京・神奈川） ---
    print("    connpass: 段階1 — RSS 月別検索")
    all_events = _fetch_connpass_events_rss(target_date)
    seen_urls: set[str] = {e["event_url"] for e in all_events}

    # --- 段階 2: X/SNS 言及からイベントキーワードを収集 ---
    print("    connpass: 段階2 — X/Google News からキーワード収集")
    extra_keywords = _discover_event_keywords_from_social()

    # --- 段階 3: 発掘キーワードで connpass RSS を追加検索 ---
    # 直近 3 ヶ月・上位 12 キーワードに絞ってリクエスト数を抑制
    kw_months = search_months[:3]
    kw_added = 0
    for kw in extra_keywords[:12]:
        new_events = _search_connpass_rss_by_keyword(kw, kw_months, seen_urls)
        all_events.extend(new_events)
        kw_added += len(new_events)
    if kw_added:
        print(f"    connpass: 段階3 — キーワード追加検索 {kw_added} 件追加")

    # --- 段階 4 (任意): connpass v2 API で補完 ---
    api_key = os.environ.get("CONNPASS_API_KEY", "")
    if api_key:
        print("    connpass: 段階4 — API v2 で補完")
        seen_ids: set[int] = set()
        for pref in CONNPASS_TARGET_PREFECTURES:
            params = {
                "keyword": pref,
                "count": CONNPASS_API_FETCH_COUNT,
                "order": 2,
                "started_at_gte": target_dt.strftime("%Y-%m-%d"),
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
                print(f"    connpass API ({pref}): {data.get('results_returned', 0)} 件取得")

                for event in data.get("events", []):
                    event_id = event.get("id")
                    if event_id and event_id in seen_ids:
                        continue
                    if event_id:
                        seen_ids.add(event_id)

                    started_at_str = event.get("started_at", "")
                    if not started_at_str:
                        continue
                    try:
                        event_dt = datetime.fromisoformat(
                            started_at_str.replace("Z", "+00:00")
                        ).astimezone(JST)
                    except (ValueError, TypeError):
                        continue

                    if event_dt < target_dt or event_dt > end_dt:
                        continue

                    accepted = event.get("accepted", 0) or 0
                    limit = event.get("limit", 0) or 0
                    if limit > 0 and accepted >= limit:
                        continue

                    series_title = ""
                    if isinstance(event.get("series"), dict):
                        series_title = event["series"].get("title", "")

                    event_url = event.get("url") or event.get("event_url", "")
                    if event_url in seen_urls:
                        continue

                    event_dict = {
                        "title": event.get("title", "").strip(),
                        "catch": event.get("catch", "").strip(),
                        "event_url": event_url,
                        "started_at": event_dt.strftime("%Y/%m/%d %H:%M"),
                        "place": event.get("place", "").strip(),
                        "address": event.get("address", "").strip(),
                        "accepted": accepted,
                        "limit": limit,
                        "series": series_title,
                    }
                    if not _is_it_event(event_dict):
                        continue
                    seen_urls.add(event_url)
                    all_events.append(event_dict)
            except Exception as e:
                print(f"    connpass API ({pref}): 取得失敗 ({e})")

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
    "claude-opus-4-6",
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
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "ビジネスニュース（日本語 + 英語ソース）",
    },
    {
        "key": "community",
        "header": "## 5. コミュニティイベント情報（東京・神奈川）",
        "system": (
            "あなたは IT コミュニティイベント情報の専門ライターです。"
            "提供されたデータを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
            "IT 関連（クラウド、AI、DevOps、セキュリティ、プログラミング、インフラ等）のイベントのみを対象とし、"
            "IT と無関係なイベント（スポーツ、料理、育児、不動産、エンタメ等）は除外してください。"
        ),
        "instruction": (
            "以下の connpass イベントデータと参加レポート・イベント宣伝記事を元に"
            "「## 5. コミュニティイベント情報（東京・神奈川）」セクションを作成してください。\n\n"
            "【重要】IT 関連のイベント・レポートのみを含めてください。"
            "対象: クラウド（Azure・AWS・GCP）、AI/ML、DevOps/SRE、セキュリティ、プログラミング、"
            "インフラ、データエンジニアリング、AIOps、FinOps、MLOps などの IT コミュニティ。"
            "除外: スポーツ、料理、音楽、育児、不動産、ゲーム（IT 系除く）、その他 IT 無関係のイベント。\n\n"
            "先頭に「## 5. コミュニティイベント情報（東京・神奈川）」を出力し、"
            "以下の 2 サブセクション構成で出力してください。\n\n"
            "### 📅 申し込み受付中のイベント\n\n"
            "connpass イベントデータから申し込み可能な近日開催の IT 関連イベントを箇条書きで列挙してください。"
            "各イベントに「イベント名（リンク付き）」「開催日時」「場所」「概要」"
            "「参加状況（申込数/定員）」を記載してください。"
            "IT 関連イベントがない場合は「現在取得できるイベント情報はありません」と記載してください。\n\n"
            "### 📝 参加レポート・イベント宣伝まとめ\n\n"
            "参加レポートデータには Zenn・Qiita・はてなブックマーク などで公開された"
            "IT 系勉強会・コミュニティイベントの参加レポート、開催レポート、イベント告知記事が含まれます。"
            "IT 関連のもののみをまとめ、各記事を次の形式で構成してください"
            "（各項目の間には必ず空行と「---」区切りを入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**参考リンク**: [タイトル](URL)\n\n---\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、サブセクション末尾に締めの文章は入れないでください。"
            "参考リンクは提供されたソースの URL をそのまま使用してください。"
            "IT 関連のレポートがない場合は「現在取得できる参加レポート情報はありません」と記載してください。\n\n"
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


def compute_since(target_date: str) -> datetime:
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    return target_dt - timedelta(days=1) + timedelta(hours=7, minutes=30)


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_daily_update.py YYYYMMDD")
        sys.exit(1)

    target_date = sys.argv[1]
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    # 前日 7:30 JST 以降の記事を対象とする
    since = compute_since(target_date)

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

    # 生成・リンク検証・再生成とは独立したコンテンツ検証プロセス
    print("\nコンテンツを検証中...")
    article = verify_content(article)

    output_dir = "updates"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
