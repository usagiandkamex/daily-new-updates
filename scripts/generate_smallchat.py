"""
テクニカル雑談生成スクリプト

SNS を中心に IT 関連の話題を収集し、
GitHub Copilot (Claude Opus) / Azure OpenAI / OpenAI API でマークダウン記事を生成する。
"""

import os
import re
import sys
from datetime import datetime, timedelta

import feedparser
import requests
from openai import AzureOpenAI, OpenAI
from openai import OpenAIError

import article_generator_shared as _ags
from article_generator_shared import (
    HTTP_HEADERS,
    GENERAL_NEWS_FEEDS,
    JST,
    SourceUrlTracker,
    _RSS_CONTENT_TYPES,
    _LINK_LABEL_RE,
    _resolve_google_news_url,
    _validate_url,
    _search_alternative_url,
    _format_bare_reference_links,
    validate_links,
    verify_content,
)


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
    # Azure 関連情報は Microsoft 公式ソースのみを使用する。
    # 他ベンダーや非公式ニュース（Google News・Reddit・Qiita 等）は意図的に除外している。
    "azure": [
        {"name": "Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
        {"name": "Azure Release Communications", "url": "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"},
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

# HTTP_HEADERS・GENERAL_NEWS_FEEDS・_RSS_CONTENT_TYPES・_LINK_LABEL_RE は
# article_generator_shared から一括インポート済み。

MAX_ARTICLES_PER_CATEGORY = 10

# 記事の最大許容年齢（日数）。日付のない記事はすべて除外する。
MAX_ARTICLE_AGE_DAYS = 30

# カテゴリごとの記事数上限オーバーライド（指定なし時は MAX_ARTICLES_PER_CATEGORY を使用）
_CATEGORY_ARTICLE_CAPS: dict[str, int] = {
    "techblog_ja": 15,
    "techblog_en": 15,
}

# --- URL 解決 -------------------------------------------------------------------
# _resolve_google_news_url・_validate_url・_search_alternative_url は
# article_generator_shared から一括インポート済み。

# --- リンク検証・コンテンツ検証 -------------------------------------------------------
# _format_bare_reference_links・validate_links・verify_content は
# article_generator_shared から一括インポート済み。


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
    """単一の RSS/Atom フィードを取得し、since 以降の記事を返す。
    MAX_ARTICLE_AGE_DAYS より古い記事は絶対上限として除外する。
    """
    return _ags._fetch_feed(url, since, max_items=max_items, max_age_days=MAX_ARTICLE_AGE_DAYS)


def fetch_category(category: str, since: datetime) -> list[dict]:
    """カテゴリに属する全フィードから記事を収集する。"""
    return _ags.fetch_category(
        FEEDS,
        category,
        since,
        max_items_per_feed=5,
        max_age_days=MAX_ARTICLE_AGE_DAYS,
        caps=_CATEGORY_ARTICLE_CAPS,
        default_cap=MAX_ARTICLES_PER_CATEGORY,
    )


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
            "提供された Azure ニュースはすべて Microsoft 公式ソース（Azure Release Communications および Azure Blog）から取得しています。"
            "公式情報を元に、IT エンジニア向けのカジュアルな記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の Azure 関連ニュースから5〜6件程度（最大6件）のトピックを選定し、マークダウン形式で出力してください。\n"
            "先頭に「## 3. Azure」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**参考リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、参考リンクのみを [タイトル](URL) 形式のハイパーリンクで記述してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "参考リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。"
            "URL を自分で生成・変更・推測しないでください。コードブロックで囲まないこと。"
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


# _build_section_prompt は article_generator_shared の共通実装を使用する。
_build_section_prompt = _ags._build_section_prompt


def generate_section(
    client,
    model: str,
    section_def: dict,
    data: "list[dict]",
    since: "datetime | None" = None,
) -> str:
    """1 セクション分の記事を LLM で生成する。"""
    return _ags.generate_section(
        client,
        model,
        section_def,
        data,
        since=since,
        max_input_chars=SECTION_MAX_INPUT_CHARS,
        default_max_input=20_000,
        max_output_tokens=SECTION_MAX_OUTPUT_TOKENS,
        temperature=0.5,
    )


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
