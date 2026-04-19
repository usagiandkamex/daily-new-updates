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

from article_generator_shared import SourceUrlTracker

JST = timezone(timedelta(hours=9))

# --- ニュースソース定義 ---------------------------------------------------------------

FEEDS = {
    # --- Microsoft ---
    "microsoft": [
        {"name": "Reddit Microsoft", "url": "https://www.reddit.com/r/microsoft/.rss"},
        {"name": "Reddit Windows", "url": "https://www.reddit.com/r/Windows11/.rss"},
        {"name": "はてなブックマーク Microsoft", "url": "https://b.hatena.ne.jp/search/tag?q=Microsoft&mode=rss"},
        {"name": "X(旧Twitter) Microsoft話題 JP", "url": "https://news.google.com/rss/search?q=X+%E6%97%A7Twitter+Microsoft+%E3%82%A8%E3%83%B3%E3%82%B8%E3%83%8B%E3%82%A2+%E8%A9%B1%E9%A1%8C&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Microsoft", "url": "https://news.google.com/rss/search?q=Microsoft+latest&hl=en&gl=US&ceid=US:en"},
        {"name": "Reddit Surface", "url": "https://www.reddit.com/r/Surface/.rss"},
        {"name": "Publickey", "url": "https://www.publickey1.jp/atom.xml"},
        {"name": "Qiita Microsoft", "url": "https://qiita.com/tags/microsoft/feed"},
        {"name": "Google News Microsoft Japan", "url": "https://news.google.com/rss/search?q=Microsoft+%E6%97%A5%E6%9C%AC&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Windows", "url": "https://news.google.com/rss/search?q=Windows+update+new&hl=en&gl=US&ceid=US:en"},
        {"name": "Microsoft Blog", "url": "https://blogs.microsoft.com/feed/"},
        {"name": "Microsoft Japan Blog", "url": "https://news.microsoft.com/ja-jp/feed/"},
        {"name": "Microsoft Developer Blog", "url": "https://devblogs.microsoft.com/feed/"},
    ],
    # --- AI ---
    "ai": [
        {"name": "Reddit MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/.rss"},
        {"name": "Reddit LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/.rss"},
        {"name": "はてなブックマーク AI", "url": "https://b.hatena.ne.jp/search/tag?q=AI&mode=rss"},
        {"name": "X(旧Twitter) AI話題 JP", "url": "https://news.google.com/rss/search?q=X+%E6%97%A7Twitter+AI+%E4%BA%BA%E5%B7%A5%E7%9F%A5%E8%83%BD+%E8%A9%B1%E9%A1%8C&hl=ja&gl=JP&ceid=JP:ja"},
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
        {"name": "X(旧Twitter) Azure話題 JP", "url": "https://news.google.com/rss/search?q=X+%E6%97%A7Twitter+Azure+%E8%A9%B1%E9%A1%8C+%E3%82%A8%E3%83%B3%E3%82%B8%E3%83%8B%E3%82%A2&hl=ja&gl=JP&ceid=JP:ja"},
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
        {"name": "X(旧Twitter) セキュリティ話題 JP", "url": "https://news.google.com/rss/search?q=X+%E6%97%A7Twitter+%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3+%E8%84%86%E5%BC%B1%E6%80%A7+IT&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News Cybersecurity", "url": "https://news.google.com/rss/search?q=cybersecurity+vulnerability&hl=en&gl=US&ceid=US:en"},
        {"name": "Qiita セキュリティ", "url": "https://qiita.com/tags/security/feed"},
        {"name": "Reddit InfoSec", "url": "https://www.reddit.com/r/InfoSecNews/.rss"},
        {"name": "Google News サイバーセキュリティ JP", "url": "https://news.google.com/rss/search?q=%E3%82%B5%E3%82%A4%E3%83%90%E3%83%BC%E6%94%BB%E6%92%83+%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "INTERNET Watch", "url": "https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf"},
        {"name": "Slashdot Security", "url": "https://slashdot.org/index.rss"},
        {"name": "Google News Wiz Research", "url": "https://news.google.com/rss/search?q=wiz+security+vulnerability+cloud&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News Project Zero", "url": "https://news.google.com/rss/search?q=Google+Project+Zero+security+vulnerability&hl=en&gl=US&ceid=US:en"},
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
        {"name": "Google Cloud Blog", "url": "https://cloud.google.com/feeds/gcp-blog-atom.xml"},
        {"name": "AWS News Blog", "url": "https://aws.amazon.com/blogs/aws/feed/"},
        {"name": "Google Blog", "url": "https://blog.google/rss/"},
        {"name": "Google News Google Cloud JP", "url": "https://news.google.com/rss/search?q=Google+Cloud+%E6%97%A5%E6%9C%AC+%E6%9C%80%E6%96%B0&hl=ja&gl=JP&ceid=JP:ja"},
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
        {"name": "Datadog Engineering Blog", "url": "https://www.datadoghq.com/blog/engineering/feed.xml"},
        {"name": "The New Stack", "url": "https://thenewstack.io/feed/"},
        {"name": "Google News Datadog Dynatrace AIOps", "url": "https://news.google.com/rss/search?q=Datadog+OR+Dynatrace+AIOps+observability+case+study&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News ServiceNow AIOps", "url": "https://news.google.com/rss/search?q=ServiceNow+AIOps+ITSM+automation+AI&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News SRE overseas case study", "url": "https://news.google.com/rss/search?q=SRE+site+reliability+engineering+Google+Netflix+Uber+case+study&hl=en&gl=US&ceid=US:en"},
        {"name": "DevOps.com", "url": "https://devops.com/feed/"},
        {"name": "DZone DevOps", "url": "https://dzone.com/devops-tutorials-tools-news/feed"},
        {"name": "GitLab Blog", "url": "https://about.gitlab.com/blog/feed.xml"},
        {"name": "Google News DevOps JP", "url": "https://news.google.com/rss/search?q=DevOps+CI%2FCD+%E8%87%AA%E5%8B%95%E5%8C%96+%E9%96%8B%E7%99%BA%E9%81%8B%E7%94%A8&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News DevOps CI/CD EN", "url": "https://news.google.com/rss/search?q=DevOps+CI+CD+pipeline+GitOps+best+practices&hl=en&gl=US&ceid=US:en"},
    ],
    # --- 日本企業テックブログ ---
    "techblog_ja": [
        {"name": "Cybozu Inside Out", "url": "https://blog.cybozu.io/feed"},
        {"name": "Mercari Engineering Blog", "url": "https://engineering.mercari.com/blog/feed.xml"},
        {"name": "LINE Engineering Blog", "url": "https://engineering.linecorp.com/ja/feed.xml"},
        {"name": "ZOZO Tech Blog", "url": "https://techblog.zozo.com/feed"},
        {"name": "Recruit Tech Blog", "url": "https://techblog.recruit.co.jp/feed"},
        {"name": "DeNA Engineering Blog", "url": "https://engineering.dena.com/blog/index.xml"},
        {"name": "Google Japan Blog", "url": "https://japan.googleblog.com/feeds/posts/default?alt=rss"},
        {"name": "Zenn サイボウズ", "url": "https://zenn.dev/cybozu/feed"},
        {"name": "Google News 企業テックブログ", "url": "https://news.google.com/rss/search?q=%E3%82%B5%E3%82%A4%E3%83%9C%E3%82%A6%E3%82%BA+OR+%E3%83%A1%E3%83%AB%E3%82%AB%E3%83%AA+OR+%E3%83%AA%E3%82%AF%E3%83%AB%E3%83%BC%E3%83%88+OR+LINE+OR+ZOZO+OR+DeNA+%E3%83%86%E3%83%83%E3%82%AF%E3%83%96%E3%83%AD%E3%82%B0&hl=ja&gl=JP&ceid=JP:ja"},
    ],
    # --- 海外企業テックブログ (英語) ---
    "techblog_en": [
        {"name": "Netflix Tech Blog", "url": "https://netflixtechblog.com/feed"},
        {"name": "Uber Engineering Blog", "url": "https://eng.uber.com/feed/"},
        {"name": "Meta Engineering Blog", "url": "https://engineering.fb.com/feed/"},
        {"name": "GitHub Blog", "url": "https://github.blog/feed/"},
        {"name": "Stripe Engineering Blog", "url": "https://stripe.com/blog/engineering.rss"},
        {"name": "Airbnb Engineering Blog", "url": "https://medium.com/airbnb-engineering/feed"},
        {"name": "Discord Engineering Blog", "url": "https://discord.com/category/engineering/rss"},
        {"name": "Dev.to", "url": "https://dev.to/feed"},
        {"name": "InfoQ", "url": "https://feed.infoq.com/"},
        {"name": "Hacker News (Best)", "url": "https://hnrss.org/best"},
        {"name": "Google News Engineering Blog EN", "url": "https://news.google.com/rss/search?q=engineering+blog+tech+Netflix+OR+Uber+OR+Meta+OR+GitHub+OR+Stripe&hl=en&gl=US&ceid=US:en"},
    ],
}

HTTP_HEADERS = {
    "User-Agent": "daily-updates-bot/1.0 (GitHub Actions; +https://github.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
}

MAX_ARTICLES_PER_CATEGORY = 10

# 記事の最大許容年齢（日数）。日付のない記事はすべて除外する。
MAX_ARTICLE_AGE_DAYS = 30

# カテゴリごとの記事数上限オーバーライド（指定なし時は MAX_ARTICLES_PER_CATEGORY を使用）
_CATEGORY_ARTICLE_CAPS: dict[str, int] = {
    "techblog_ja": 15,
    "techblog_en": 15,
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
                rf'(?:\[(?:{_LINK_LABEL_RE})\]\({escaped}\)|{escaped})'
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

            # **要約** チェック
            if '**要約**' not in topic_block:
                issues.append(f"要約なし: [{section_name}] {topic_title}")

            # **参考リンク** チェック
            if '**参考リンク**' not in topic_block:
                issues.append(f"参考リンクなし: [{section_name}] {topic_title}")
            else:
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


def _fetch_feed(url: str, since: datetime, max_items: int = 5) -> list[dict]:
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    max_age_cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)

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

        # 日付のない記事は新鮮さを確認できないため除外する。
        # `since` より古い記事も除外し、MAX_ARTICLE_AGE_DAYS は将来的に
        # `since` が大幅に広げられた場合のための絶対的な上限として機能する。
        if not pub_date or pub_date < since or pub_date < max_age_cutoff:
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

    cap = _CATEGORY_ARTICLE_CAPS.get(category, MAX_ARTICLES_PER_CATEGORY)
    if len(deduped) > cap:
        print(f"  ※ {len(deduped)} 件 → {cap} 件に制限")
        deduped = deduped[:cap]
    return deduped


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


# --- ソース URL 管理 ---------------------------------------------------------------

# SourceUrlTracker を両ワークフローで共有して使用するためのモジュールレベルエイリアス。
# 実装は article_generator_shared.py の SourceUrlTracker クラスで一元管理する。
_collect_source_urls = SourceUrlTracker.collect_source_urls
_log_unsourced_reference_links = SourceUrlTracker.log_unsourced_reference_links


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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
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
            "古い情報や重複する話題は避け、直近の最新情報を優先して選定してください。"
        ),
        "instruction": (
            "以下の IT 運用・管理ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "**AIOps**（AIを活用したIT運用自動化・異常検知・予測分析・インシデント自動対応）および"
            "**SRE Agent**（AI駆動のサイト信頼性エンジニアリングエージェント）を重点的に取り上げてください。\n"
            "**DevOps**（CI/CD パイプライン・GitOps・Infrastructure as Code・デプロイ自動化）の最新プラクティスや事例も積極的に取り上げてください。\n"
            "**海外（米国・欧州）の IT 企業における AIOps・DevOps・SRE・オブザーバビリティの最新事例を積極的に含めてください。**\n"
            "特に Google・Netflix・Uber・Meta・Amazon などの大手 IT 企業の運用事例、"
            "Datadog・Dynatrace・PagerDuty・ServiceNow・GitLab・GitHub Actions などの主要ツールの最新機能や活用事例を取り上げてください。\n"
            "Microsoft Azure Monitor・System Center・Copilot for IT Operations・Azure DevOps 等の Microsoft 製品による AIOps・DevOps も優先的に含めてください。\n"
            "ITSM・エンドポイント管理・MSP・オブザーバビリティ・OpenTelemetry など IT 運用全般のトレンドも含めてください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 6. IT運用・管理」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "IT運用・管理（AIOps / ITSM / DevOps / オブザーバビリティ / 海外事例）",
    },
    {
        "key": "techblog_ja",
        "header": "## 7. 日本企業テックブログ",
        "system": (
            "あなたは日本の IT 企業テックブログのライターです。"
            "国内の技術ブログから収集した情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の日本企業テックブログの記事から5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "サイボウズ、メルカリ、LINE、ZOZO、リクルートなどの国内 IT 企業のエンジニアリングブログ記事を優先してください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 7. 日本企業テックブログ」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "日本企業テックブログ関連",
    },
    {
        "key": "techblog_en",
        "header": "## 8. 海外企業テックブログ",
        "system": (
            "あなたは海外の IT 企業テックブログのライターです。"
            "Netflix、Uber、Meta、GitHub、Stripe などの海外企業の技術ブログから収集した情報を元に、"
            "IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の海外企業テックブログの記事から5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "Netflix、Uber、Meta、GitHub、Stripe、Airbnb などの海外 IT 企業のエンジニアリングブログ記事を優先してください。\n"
            "記事が英語の場合も、内容の要約・影響は日本語で記述してください。\n"
            "情報が不足している場合は、最新のニュース系トピックを補足として追加してもかまいません。\n"
            "先頭に「## 8. 海外企業テックブログ」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "参考リンクは提供されたソースの URL をそのまま使用してください。コードブロックで囲まないこと。"
        ),
        "data_label": "海外企業テックブログ関連",
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
    "techblog_ja": 20_000,
    "techblog_en": 20_000,
}

# セクションごとの出力トークン上限
SECTION_MAX_OUTPUT_TOKENS = 3000


def _build_section_prompt(section_def: dict, data: list[dict], since: "datetime | None" = None) -> str:
    """セクション固有のユーザープロンプトを組み立てる。

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
    label = section_def.get("data_label") or "データ"
    lines.extend([
        section_def["instruction"],
        "",
        f"### {label}",
        json.dumps(data, ensure_ascii=False, indent=2),
        "",
    ])
    return "\n".join(lines)


def generate_section(
    client,
    model: str,
    section_def: dict,
    data: list[dict],
    since: "datetime | None" = None,
) -> str:
    """1 セクション分の記事を LLM で生成する。"""
    key = section_def["key"]
    max_input = SECTION_MAX_INPUT_CHARS.get(key, 20_000)

    # データが空リストの場合は LLM を呼ばずに「ありません」を返す
    if len(data) == 0:
        header = section_def.get("header", "")
        return f"{header}\n\n現在の対象期間に該当する情報はありません。"

    user_prompt = _build_section_prompt(section_def, data, since=since)
    while len(user_prompt) > max_input:
        if len(data) > 3:
            data.pop()
            user_prompt = _build_section_prompt(section_def, data, since=since)
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
    techblog_ja_news: list[dict] | None = None,
    techblog_en_news: list[dict] | None = None,
    since: "datetime | None" = None,
) -> str:
    """各セクションを個別の LLM 呼び出しで生成し、1 つの記事に組み立てる。

    セクションごとに独立した API コールを行うことで、各セクションが
    トークン上限を最大限に活用できるようにする。
    since が指定された場合、各セクションに対象期間の注意事項を付記する。
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
        "techblog_ja": techblog_ja_news if techblog_ja_news is not None else [],
        "techblog_en": techblog_en_news if techblog_en_news is not None else [],
    }

    article_parts = [f"# {formatted_date} テクニカル雑談（{slot_label}）"]

    for section_def in SECTION_DEFINITIONS:
        key = section_def["key"]
        data = section_data_map[key]
        print(f"  [{key}] セクション生成中...")
        section_text = generate_section(client, model, section_def, data, since=since)
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

    print("\n[日本企業テックブログ]")
    techblog_ja_news = fetch_category("techblog_ja", since)
    print(f"  → 合計: {len(techblog_ja_news)} 件")

    print("\n[海外企業テックブログ]")
    techblog_en_news = fetch_category("techblog_en", since)
    print(f"  → 合計: {len(techblog_en_news)} 件")

    # 後でリトライ時に重複除外するためセクションキー → 元データのマッピングを保持
    section_data_map = {
        "microsoft": microsoft_news,
        "ai": ai_news,
        "azure": azure_news,
        "cloud": cloud_news,
        "security": security_news,
        "itops": itops_news,
        "techblog_ja": techblog_ja_news,
        "techblog_en": techblog_en_news,
    }

    # ソースデータ URL を収集（LLM 生成後の参考リンク検証に使用）
    source_urls = _collect_source_urls(
        microsoft_news, ai_news, azure_news, cloud_news,
        security_news, itops_news, techblog_ja_news, techblog_en_news,
    )
    print(f"\nソース URL 収集完了: {len(source_urls)} 件")

    print("\n記事を生成中（セクションごとに個別生成）...")
    llm_clients = create_llm_clients()
    article = None
    last_error = None
    for client, model in llm_clients:
        try:
            print(f"  モデル: {model}")
            article = generate_article(
                client, model, target_date, slot,
                microsoft_news, ai_news, azure_news, security_news, cloud_news, itops_news,
                techblog_ja_news=techblog_ja_news,
                techblog_en_news=techblog_en_news,
                since=since,
            )
            break
        except OpenAIError as e:
            print(f"  ⚠ {model} での生成に失敗しました ({e})")
            last_error = e
    if article is None:
        raise RuntimeError(f"全ての LLM プロバイダーで生成に失敗しました。最後のエラー: {last_error}")

    print("\nリンクを検証中...")
    article = _format_bare_reference_links(article)

    # ソース外参考リンクを検出・ログ出力（デバッグ・品質確認用）
    print("\nソース外参考リンクを確認中...")
    _log_unsourced_reference_links(article, source_urls)

    article = validate_links(article)

    # リンク除去で空になったセクションを時間窓を広げて再生成する
    print("\n空セクションの確認...")
    extended_since = target_dt - timedelta(hours=24)
    article = _regenerate_empty_sections(
        article, SECTION_DEFINITIONS, section_data_map, extended_since, llm_clients
    )

    # 生成・リンク検証・再生成とは独立したコンテンツ検証プロセス
    print("\nコンテンツを検証中...")
    article = verify_content(article)

    output_dir = "smallchat"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date}_{slot}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
