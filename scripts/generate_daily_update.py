"""
デイリーアップデート生成スクリプト

複数の RSS/Atom フィードで最新ニュースを取得し、
GitHub Copilot (Claude Opus) / Azure OpenAI / OpenAI API でマークダウン記事を生成する。
"""

import os
import re
import sys
import calendar
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote_plus

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
    # --- Azure ---
    # Azure Updates は Microsoft 公式ソースのみを使用する
    # （公式 Azure Updates / モデル更新情報 / 公式ブログの Update 関連情報）。
    # 他ベンダーや非公式ニュース（Google News 等）は意図的に除外している。
    "azure": [
        {"name": "Azure Release Communications", "url": "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"},
        {"name": "Azure Blog", "url": "https://azure.microsoft.com/en-us/blog/feed/"},
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
        # Anthropic Engineering Blog は公式 RSS を提供していないため、
        # Google News RSS で anthropic.com/engineering 配下の記事に絞り込む
        {"name": "Google News - Anthropic Engineering", "url": "https://news.google.com/rss/search?q=site%3Aanthropic.com%2Fengineering&hl=en&gl=US&ceid=US:en"},
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

# HTTP_HEADERS・GENERAL_NEWS_FEEDS・_RSS_CONTENT_TYPES・_LINK_LABEL_RE は
# article_generator_shared から一括インポート済み。

# --- URL 解決 -------------------------------------------------------------------
# _resolve_google_news_url・_validate_url・_search_alternative_url は
# article_generator_shared から一括インポート済み。

# --- リンク検証・コンテンツ検証 -------------------------------------------------------
# _format_bare_reference_links・validate_links・verify_content は
# article_generator_shared から一括インポート済み。

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
      1. 拡張時間窓（直近 1 か月、EXTENDED_LOOKBACK_DAYS）でカテゴリ専用フィードを再取得して LLM 再生成
      2. official_only=True でないセクションのみ汎用 IT ニュースフィードで LLM 再生成
         （Azure 等の公式ソース限定セクションはこのフォールバックをスキップする）
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

        # official_only セクション（Azure 等）は公式ソース以外へのフォールバックを行わない
        is_official_only = section_def.get("official_only", False)

        # カテゴリ専用フィードに新規データがなければ汎用ニュースにフォールバック
        if not new_items and not is_official_only:
            print(f"  [{key}] 専用フィードに新しいデータなし。汎用ニュースにフォールバックします...")
            new_items = fetch_general_news(extended_since, exclude_urls=original_urls)
        elif not new_items and is_official_only:
            print(f"  [{key}] 専用フィードに新しいデータなし（公式ソース限定のため汎用ニュースはスキップ）。")

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


# 空セクションのフォールバック時に時間窓を広げる日数。
# デイリーアップデートは毎日 07:30 JST に実行される（.github/workflows/daily-update.yml）ため、
# 通常の収集窓は since（前日 07:30 JST、約24時間 ＝ 直近 1〜2 日）。
# 通常窓で記事が見つからずセクションが空になった場合のみ、
# _regenerate_empty_sections が extended_since = target_dt - EXTENDED_LOOKBACK_DAYS まで
# 範囲を広げて再取得を試みる。それでも見つからなければ「情報なし」を出力する。
# 30 日（約 1 か月）は、ニッチなカテゴリでも 1 か月以内には何らかの更新がある想定で設定している。
EXTENDED_LOOKBACK_DAYS = 30

# 記事の最大許容年齢（日数）。これより古い記事はフィードに含まれていても出力しない。
# Microsoft 等の一部フィードが数年前の古い情報（SB 等）を返すことがあるため設定している。
MAX_ARTICLE_AGE_DAYS = 30


def _fetch_feed(url: str, since: datetime, max_items: int = 10) -> list[dict]:
    """単一の RSS/Atom フィードを取得し、since 以降の記事を返す。

    日付のない記事は新鮮さを確認できないため、shared 実装側で常に除外される。
    MAX_ARTICLE_AGE_DAYS より古い記事は since 以降であっても除外する。
    """
    return _ags._fetch_feed(url, since, max_items=max_items, max_age_days=MAX_ARTICLE_AGE_DAYS)


def fetch_category(category: str, since: datetime) -> list[dict]:
    """カテゴリに属する全フィードから記事を収集する。"""
    return _ags.fetch_category(FEEDS, category, since, max_age_days=MAX_ARTICLE_AGE_DAYS)



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


# --- ソース URL 管理 ---------------------------------------------------------------

# SourceUrlTracker を両ワークフローで共有して使用するためのモジュールレベルエイリアス。
# 実装は article_generator_shared.py の SourceUrlTracker クラスで一元管理する。
_collect_source_urls = SourceUrlTracker.collect_source_urls
_log_unsourced_reference_links = SourceUrlTracker.log_unsourced_reference_links
_replace_unsourced_reference_links = SourceUrlTracker.replace_unsourced_reference_links
_verify_link_source_match = SourceUrlTracker.verify_link_source_match


CONNPASS_API_URL = "https://connpass.com/api/v2/events/"
CONNPASS_RSS_URL = "https://connpass.com/search/"
CONNPASS_TARGET_PREFECTURES = ["東京都", "神奈川県"]
# 最終出力に含めるイベント数の上限
CONNPASS_MAX_EVENTS = 20
# API 1 リクエストで取得する最大件数（connpass v2 API の上限は 100）
CONNPASS_API_FETCH_COUNT = 100
# 同一 (pref, ym) でページングする最大ページ数（安全装置）。
# count=100 × 10 ページ = 最大 1000 件/月 までカバーする。
CONNPASS_API_MAX_PAGES = 10
# 遡及日数（実行日から何日前まで検索対象にするか）
CONNPASS_LOOKBACK_DAYS = 90

# connpass RSS 検索の都道府県ID（https://connpass.com/search/?pref_id=XX 参照）
# connpass API v1 は 2024 年 7 月末に終了。RSS 検索エンドポイントが同じ pref_id を受け付ける。
_CONNPASS_PREFECTURE_IDS: dict[str, int] = {
    "東京都": 13,
    "神奈川県": 14,
}

# Google News RSS で X(Twitter) 発のイベント告知を間接的に検索するクエリ群
# connpass 以外のプラットフォームも対象に含め、幅広くイベント情報を収集する
_CONNPASS_SOCIAL_DISCOVERY_QUERIES = [
    # connpass
    "IT 勉強会 東京 connpass 申込",
    "エンジニア イベント 東京 ハンズオン connpass",
    "JAWS AWS 東京 勉強会 開催",
    "Azure クラウド 東京 勉強会 コミュニティ",
    "Kubernetes Docker Python 東京 勉強会",
    "神奈川 IT コミュニティ 勉強会 申込",
    # Doorkeeper
    "エンジニア イベント 東京 doorkeeper 開催",
    "IT 技術 勉強会 doorkeeper 申込受付",
    # TECH PLAY
    "エンジニア セミナー 東京 techplay",
    "IT 技術 イベント techplay 開催予定",
    # Findy
    "エンジニア イベント 東京 findy 開催",
    "IT 技術 勉強会 findy 申込",
    # Codezine
    "エンジニア セミナー 東京 codezine",
    "IT 技術 イベント codezine 開催",
    # プラットフォーム横断
    "エンジニア ミートアップ 東京 開催",
    "生成AI LLM ハンズオン 東京 勉強会",
    "クラウド セキュリティ 東京 イベント 申込",
    "X Twitter エンジニア 勉強会 東京 開催",
]

# connpass RSS 追加検索の種になる既知 IT コミュニティ・技術キーワード
_CONNPASS_COMMUNITY_SEED_KEYWORDS = [
    # コミュニティ・グループ
    "JAWS",
    "JAWSUG",
    "GCPUG",
    "CloudNative",
    "Azure User Group",
    # DevOps・SRE・プラットフォーム
    "SRE",
    "DevOps",
    "Platform Engineering",
    "FinOps",
    "MLOps",
    # AI・ML
    "LLM",
    "生成AI",
    "機械学習",
    "RAG",
    # セキュリティ
    "セキュリティ",
    "ゼロトラスト",
    # 言語・フレームワーク
    "Python",
    "TypeScript",
    "Rust",
    "Go言語",
    "React",
    # インフラ・クラウド
    "Kubernetes",
    "HashiCorp",
    "データエンジニアリング",
]

# 発掘クエリ1件あたりに処理する RSS エントリの上限（クエリ数×この値がリクエスト負荷に影響）
_SOCIAL_DISCOVERY_MAX_ENTRIES_PER_QUERY = 8
# キーワード追加検索で対象とする直近月数（リクエスト数 = キーワード数 × この値）
_KEYWORD_SEARCH_MONTHS = 3
# キーワード追加検索で使用するキーワード数の上限
_MAX_KEYWORDS_TO_SEARCH = 20

# connpass 以外の IT イベントプラットフォームの Atom/RSS フィード
# 東京・神奈川エリアの IT イベントを広くカバーするために使用する
# location_filter=True のフィードは、タイトル/概要に東京・神奈川・オンライン関連語が
# 含まれるエントリのみを通過させる（全国対象フィードの混入防止）
# event_filter=True のフィードは、タイトル/概要にイベント告知語が含まれるエントリのみ通過させる
#   （汎用記事 RSS で記事がイベント一覧に混入するのを防ぐ）
# started_at_from_published=True のフィードは、published_parsed をイベント開始日時のプロキシとして使う
#   （connpass グループ RSS はイベントエントリの published がイベント開催日時に対応するため）
_IT_EVENT_PLATFORM_FEEDS: list[dict] = [
    # Doorkeeper — タグ別 Atom フィード（認証不要）
    {"name": "Doorkeeper エンジニア", "url": "https://www.doorkeeper.jp/tags/エンジニア.atom"},
    {"name": "Doorkeeper 勉強会",     "url": "https://www.doorkeeper.jp/tags/勉強会.atom"},
    {"name": "Doorkeeper 東京",       "url": "https://www.doorkeeper.jp/tags/東京.atom"},
    {"name": "Doorkeeper オンライン", "url": "https://www.doorkeeper.jp/tags/オンライン.atom"},
    # TECH PLAY — 全国対象 Atom フィード。location_filter で東京・神奈川・オンラインに限定
    {"name": "TECH PLAY", "url": "https://techplay.jp/atom/events", "location_filter": True},
    # Findy — connpass グループ RSS（Findy 主催エンジニア向けイベント）
    # published_parsed が開催日時のプロキシとして使えるため started_at_from_published=True
    {"name": "Findy", "url": "https://findy.connpass.com/rss", "started_at_from_published": True},
    # Codezine — connpass グループ RSS（Developers Summit / CodeZine Night 等の参加募集イベント）
    # 汎用ニュース RSS（codezine.jp/rss/）は記事と混在するため使用しない。connpass グループ RSS を使用する。
    # published_parsed が開催日時のプロキシとして使えるため started_at_from_published=True
    {"name": "Codezine", "url": "https://codezine.connpass.com/rss", "started_at_from_published": True},
]

# location_filter=True のフィードに適用する地域キーワード（小文字比較）
_LOCATION_FILTER_KEYWORDS: frozenset[str] = frozenset([
    "東京", "tokyo",
    "神奈川", "kanagawa", "横浜", "yokohama",
    "オンライン", "online", "リモート", "remote",
])

# event_filter=True のフィードに適用するイベント告知語（小文字比較）
# タイトル/概要のいずれかに含まれる場合のみイベントとして通過させる
_EVENT_FILTER_KEYWORDS: frozenset[str] = frozenset([
    "イベント", "セミナー", "勉強会", "ウェビナー", "webinar",
    "ハンズオン", "ミートアップ", "meetup", "カンファレンス", "conference",
    "ワークショップ", "workshop", "講演", "登壇", "開催",
])

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


def _parse_rss_event_started_at(entry) -> str:
    """feedparser エントリから開催日時文字列を取得する。

    connpass RSS の published_parsed をイベント開始日時のプロキシとして使用する。
    日時情報が取得できない場合、または変換に失敗した場合は空文字列を返す。
    """
    pub = entry.get("published_parsed")
    if pub is None:
        return ""
    try:
        event_dt = datetime(*pub[:6], tzinfo=timezone.utc).astimezone(JST)
        return event_dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        return ""


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
    """connpass RSS 検索で都道府県・月別に IT イベントを取得する（認証不要）。

    connpass API v1 は 2024 年 7 月末に終了しており利用不可。
    代わりに connpass RSS 検索エンドポイント（https://connpass.com/search/?format=rss）を使用。
    pref_id パラメータで都道府県を指定することで東京都・神奈川県のイベントのみを確実に取得できる。
    また online=1 パラメータでオンライン開催イベントも別途取得する。
    旧実装の keyword による都道府県名の文字列検索は、イベントのタイトルや説明文に都道府県名が
    含まれることがほとんどないため、常に 0 件になっていた。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    start_dt = target_dt - timedelta(days=CONNPASS_LOOKBACK_DAYS)

    events = []
    seen_urls: set[str] = set()

    # 遡及開始月から実行日の月まで、月単位で列挙する
    search_months = []
    y, m = start_dt.year, start_dt.month
    while (y, m) <= (target_dt.year, target_dt.month):
        search_months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    for pref in CONNPASS_TARGET_PREFECTURES:
        pref_id = _CONNPASS_PREFECTURE_IDS.get(pref)
        if pref_id is None:
            print(f"    connpass RSS ({pref}): pref_id 未定義、スキップ")
            continue
        for ym in search_months:
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
                    if not _is_it_event({"title": title, "catch": desc}):
                        continue
                    seen_urls.add(url)
                    events.append(
                        {
                            "title": title,
                            "catch": desc[:200],
                            "event_url": url,
                            "started_at": _parse_rss_event_started_at(entry),
                            "place": "",
                            "address": "",
                            "accepted": 0,
                            "limit": 0,
                            "series": "",
                        }
                    )
                    count += 1
                print(f"    connpass RSS ({pref} {ym}): {count} 件取得")
            except Exception as e:
                print(f"    connpass RSS ({pref} {ym}): 取得失敗 ({e})")

    # オンライン開催イベントを追加検索（online=1 パラメータ、都道府県不問）
    for ym in search_months:
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
                if not _is_it_event({"title": title, "catch": desc}):
                    continue
                seen_urls.add(url)
                events.append(
                    {
                        "title": title,
                        "catch": desc[:200],
                        "event_url": url,
                        "started_at": _parse_rss_event_started_at(entry),
                        "place": "オンライン",
                        "address": "",
                        "accepted": 0,
                        "limit": 0,
                        "series": "",
                    }
                )
                count += 1
            print(f"    connpass RSS (オンライン {ym}): {count} 件取得")
        except Exception as e:
            print(f"    connpass RSS (オンライン {ym}): 取得失敗 ({e})")

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
            for entry in feed.entries[:_SOCIAL_DISCOVERY_MAX_ENTRIES_PER_QUERY]:
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
                        "started_at": _parse_rss_event_started_at(entry),
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


def _fetch_other_platform_events(
    seen_urls: set[str],
) -> list[dict]:
    """Doorkeeper・TECH PLAY・connpass グループ RSS など、connpass の月別検索/RSS 検索以外のフィードから IT イベントを取得する。

    _IT_EVENT_PLATFORM_FEEDS に定義された Atom/RSS フィードを feedparser で取得し、
    IT 関連のイベントを返す。
    seen_urls に登録済みの URL は重複として除外する。
    location_filter=True が設定されたフィードは、タイトル/概要に東京・神奈川・オンライン
    関連語を含むエントリのみ通過させる。
    event_filter=True が設定されたフィードは、タイトル/概要にイベント告知語が含まれる
    エントリのみ通過させる（汎用記事フィードからの記事混入を防ぐ）。
    started_at_from_published=True が設定されたフィードは、published_parsed を
    イベント開始日時のプロキシとして started_at に設定する（connpass グループ RSS 向け）。
    ネットワーク障害や未対応フィード形式は個別に無視し、他フィードの取得を続行する。
    """
    events = []
    for feed_def in _IT_EVENT_PLATFORM_FEEDS:
        name: str = feed_def.get("name") or ""
        try:
            url: str = feed_def.get("url") or ""
            if not url:
                continue
            use_location_filter: bool = bool(feed_def.get("location_filter"))
            use_event_filter: bool = bool(feed_def.get("event_filter"))
            use_started_at_from_published: bool = bool(feed_def.get("started_at_from_published"))
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=20)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            count = 0
            for entry in feed.entries:
                event_url = entry.get("link", "")
                if not event_url or event_url in seen_urls:
                    continue
                title = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()
                combined = (title + " " + summary).lower()

                # location_filter が設定されたフィードはタイトル/概要で地域を絞る
                if use_location_filter:
                    if not any(kw in combined for kw in _LOCATION_FILTER_KEYWORDS):
                        continue

                # event_filter が設定されたフィードはイベント告知語を要求する
                if use_event_filter:
                    if not any(kw in combined for kw in _EVENT_FILTER_KEYWORDS):
                        continue

                if not _is_it_event({"title": title, "catch": summary}):
                    continue

                started_at = _parse_rss_event_started_at(entry) if use_started_at_from_published else ""
                seen_urls.add(event_url)
                events.append(
                    {
                        "title": title,
                        "catch": summary[:200] if summary else "",
                        "event_url": event_url,
                        "started_at": started_at,
                        "place": "",
                        "address": "",
                        "accepted": 0,
                        "limit": 0,
                        "series": name,
                    }
                )
                count += 1
            if count:
                print(f"    {name}: {count} 件取得")
        except Exception as e:
            print(f"    {name or '(不明)'}: 取得失敗 ({e})")
    return events


def fetch_connpass_events(
    target_date: str,
    prev_event_urls: "set[str] | None" = None,
) -> list[dict]:
    """connpassから東京・神奈川の近日開催コミュニティイベントを取得する（多段検索）。

    API キー不要の多段検索で upcoming IT イベントを発掘する:

    1. connpass RSS 月別 × 都道府県 検索（東京・神奈川、pref_id 指定）+ オンラインイベント検索（online=1）
       ※ connpass API v1 は 2024 年 7 月末終了。RSS 検索エンドポイントが pref_id / online に対応。
    2. Google News / X(Twitter) 言及からコミュニティキーワードを収集
    3. 収集キーワードで connpass RSS を追加検索（直近 1 ヶ月、上位 20 キーワード）
    4. Doorkeeper / TECH PLAY / Findy / Codezine など connpass 以外のプラットフォームから取得
    5. CONNPASS_API_KEY が設定されている場合は v2 API でも補完する

    ステップ 1〜4 は API キー不要のため、CONNPASS_API_KEY が未設定でも動作する。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    start_dt = target_dt - timedelta(days=CONNPASS_LOOKBACK_DAYS)
    # 取得対象の未来側上限（実行日から CONNPASS_LOOKBACK_DAYS 日先まで）
    end_dt = target_dt + timedelta(days=CONNPASS_LOOKBACK_DAYS)

    # 検索月リストを構築（全段階で共用）：遡及開始月〜実行日の月
    search_months: list[str] = []
    y, m = start_dt.year, start_dt.month
    while (y, m) <= (target_dt.year, target_dt.month):
        search_months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    # --- 段階 1: connpass RSS 月別 × 都道府県 検索（東京・神奈川） ---
    print("    connpass: 段階1 — RSS 月別 × 都道府県 検索")
    all_events = _fetch_connpass_events_rss(target_date)
    seen_urls: set[str] = {e["event_url"] for e in all_events}

    # --- 段階 2: X/SNS 言及からイベントキーワードを収集 ---
    print("    connpass: 段階2 — X/Google News からキーワード収集")
    extra_keywords = _discover_event_keywords_from_social()

    # --- 段階 3: 発掘キーワードで connpass RSS を追加検索 ---
    # 直近 3 ヶ月・上位 20 キーワードに絞ってリクエスト数を抑制
    kw_months = search_months[:_KEYWORD_SEARCH_MONTHS]
    kw_added = 0
    for kw in extra_keywords[:_MAX_KEYWORDS_TO_SEARCH]:
        new_events = _search_connpass_rss_by_keyword(kw, kw_months, seen_urls)
        all_events.extend(new_events)
        kw_added += len(new_events)
    if kw_added:
        print(f"    connpass: 段階3 — キーワード追加検索 {kw_added} 件追加")

    # --- 段階 4: 他プラットフォーム（Doorkeeper / TECH PLAY / Findy / Codezine など）から取得 ---
    print("    connpass: 段階4 — 他プラットフォームから取得")
    other_events = _fetch_other_platform_events(seen_urls)
    all_events.extend(other_events)

    # --- 段階 5 (任意): connpass v2 API で補完 ---
    # connpass v2 API（https://connpass.com/about/api/v2/）の公式パラメータのみ使用する。
    # サポートされる日付絞り込みは ym（YYYYMM）/ ymd（YYYYMMDD）のみで、
    # started_at_gte / accepted_end_at_gte 等の v1 系パラメータは存在しない。
    # 未文書パラメータは API 側で無視されるため、当日以降のイベントは ym を月単位で指定して取得する。
    # order=2 は「開催日時順（昇順）」を意味する（v2 仕様）。
    api_key = os.environ.get("CONNPASS_API_KEY", "")
    if api_key:
        print("    connpass: 段階5 — API v2 で補完")
        seen_ids: set[int] = set()
        # 当月から CONNPASS_LOOKBACK_DAYS 先までの YYYYMM 一覧を構築
        api_yms: list[str] = []
        ay, am = target_dt.year, target_dt.month
        while (ay, am) <= (end_dt.year, end_dt.month):
            api_yms.append(f"{ay:04d}{am:02d}")
            am += 1
            if am > 12:
                am = 1
                ay += 1
        for pref in CONNPASS_TARGET_PREFECTURES:
            for ym in api_yms:
                # connpass v2 API は count(最大100) + start(1-indexed) でページングする。
                # results_available が count を超える月（東京都など）では、後続ページに
                # target_dt 以降のイベントが含まれることがあるため、必要な範囲をカバー
                # するまで追加取得する。安全装置として最大ページ数で打ち切る。
                start = 1
                page = 0
                max_pages = CONNPASS_API_MAX_PAGES
                while page < max_pages:
                    page += 1
                    params = {
                        "keyword": pref,
                        "ym": ym,
                        "count": CONNPASS_API_FETCH_COUNT,
                        "start": start,
                        "order": 2,
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
                        returned = int(data.get("results_returned", 0) or 0)
                        available = int(data.get("results_available", 0) or 0)
                        print(
                            f"    connpass API ({pref} {ym} p{page} start={start}): "
                            f"{returned}/{available} 件取得"
                        )
                    except Exception as e:
                        print(
                            f"    connpass API ({pref} {ym} p{page}): 取得失敗 ({e})"
                        )
                        break

                    for event in data.get("events", []):
                        # connpass v2 のイベント識別子は event_id。古いレスポンスの id にもフォールバック。
                        event_id = event.get("event_id") or event.get("id")
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
                            "title": (event.get("title") or "").strip(),
                            "catch": (event.get("catch") or "").strip(),
                            "description": (event.get("description") or "").strip(),
                            "event_url": event_url,
                            "started_at": event_dt.strftime("%Y/%m/%d %H:%M"),
                            "place": (event.get("place") or "").strip(),
                            "address": (event.get("address") or "").strip(),
                            "accepted": accepted,
                            "limit": limit,
                            "series": series_title,
                        }
                        if not _is_it_event(event_dict):
                            continue
                        seen_urls.add(event_url)
                        all_events.append(event_dict)

                    # ページング終了条件:
                    #   - 0 件返却（取り尽くした / 該当なし）
                    #   - 取得済み件数が available 以上
                    #   - count に満たない返却（最終ページ）
                    if returned <= 0:
                        break
                    fetched_total = start - 1 + returned
                    if available > 0 and fetched_total >= available:
                        break
                    if returned < CONNPASS_API_FETCH_COUNT:
                        break
                    start = fetched_total + 1

    # 過去イベントを除外し、開始日の近い順（未来の早い順）にソートする
    # started_at が空（日時不明）のイベントは有日時イベントの後に配置する
    today_str = target_dt.strftime("%Y/%m/%d")
    all_events = [
        e for e in all_events
        if not e.get("started_at") or e["started_at"][:10] >= today_str
    ]
    all_events.sort(key=lambda e: (0, e["started_at"]) if e.get("started_at") else (1, ""))

    # 前日との重複を後方に移動してから件数上限を適用する
    # こうすることで、新規イベントが十分あれば重複イベントは自然に除外される
    if prev_event_urls:
        repeated_count = sum(1 for e in all_events if e.get("event_url") in prev_event_urls)
        if repeated_count > 0:
            all_events = _deprioritize_repeated_events(all_events, prev_event_urls)
            print(f"  ※ 前日と重複する {repeated_count} 件を後方に移動しました")

    if len(all_events) > CONNPASS_MAX_EVENTS:
        print(f"  ※ connpass {len(all_events)} 件 → {CONNPASS_MAX_EVENTS} 件に制限")
        all_events = all_events[:CONNPASS_MAX_EVENTS]

    return all_events


# 除外セクションキーワード（注意事項・キャンセルポリシー等）
_EXCLUDE_HEADING_KEYWORDS = (
    "注意事項", "キャンセル", "参加条件", "持ち物", "アクセス",
    "事前準備", "禁止事項", "免責", "プライバシー", "個人情報", "お問い合わせ",
)
# マークダウン見出しパターン（プレーンテキスト description 用・h1〜h6 相当）
_EVENT_EXCLUDE_SECTION_MD_RE = re.compile(
    r"(?:^|\n)\s*#{1,6}\s*(?:" + "|".join(re.escape(kw) for kw in _EXCLUDE_HEADING_KEYWORDS) + ")",
    re.IGNORECASE,
)
# イベント概要の最大文字数（2〜3 行相当）
_EVENT_SUMMARY_MAX_LENGTH = 200


class _DescriptionHTMLParser(HTMLParser):
    """HTML description フィールドから本文テキストを抽出するパーサー。

    見出し（h1〜h6）のテキストはセクション名の混入を防ぐため除外する。
    _EXCLUDE_HEADING_KEYWORDS に含まれるキーワードを持つ見出し以降は
    テキストの収集を停止する（注意事項・キャンセルポリシー等）。
    """

    _HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._in_heading = False
        self._heading_buf: list[str] = []
        self._done = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if not self._done and tag in self._HEADING_TAGS:
            self._in_heading = True
            self._heading_buf = []

    def handle_endtag(self, tag: str) -> None:
        if self._done or tag not in self._HEADING_TAGS or not self._in_heading:
            return
        heading_text = "".join(self._heading_buf).strip()
        self._in_heading = False
        self._heading_buf = []
        if any(kw in heading_text for kw in _EXCLUDE_HEADING_KEYWORDS):
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._done:
            return
        if self._in_heading:
            self._heading_buf.append(data)
        else:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _build_event_summary(catch: str | None, description: str | None) -> str:
    """イベント説明文（HTML/テキスト）から 2〜3 行分の概要を返す。

    description が指定されている場合は HTML を解析して本文のみを抽出し、
    注意事項・キャンセルポリシーなどの除外セクション以降を切り捨てる。
    HTML エンティティは HTMLParser(convert_charrefs=True) で一段階デコードする。
    抽出結果を最大 _EVENT_SUMMARY_MAX_LENGTH 文字に制限して返す。
    description が空の場合は catch をそのまま返す。
    catch も description も空（または None）の場合は空文字列を返す。
    """
    catch = catch or ""
    description = description or ""
    desc_text = ""
    if description:
        # HTML パーサーで本文を抽出（見出しは除去し、除外セクション以降は停止）
        parser = _DescriptionHTMLParser()
        parser.feed(description)
        text = parser.get_text()
        # 除外セクション（マークダウン見出し形式）以降を切り捨て（プレーンテキスト用）
        m = _EVENT_EXCLUDE_SECTION_MD_RE.search(text)
        if m:
            text = text[: m.start()]
        # 連続する空白・改行を 1 スペースにまとめる
        text = re.sub(r"\s+", " ", text).strip()
        desc_text = text

    # description があればその本文を優先し、catch はフォールバックのみに使う
    if desc_text:
        combined = desc_text
    elif catch:
        combined = catch
    else:
        combined = ""

    # 2〜3 行分（_EVENT_SUMMARY_MAX_LENGTH 文字）に制限
    if len(combined) > _EVENT_SUMMARY_MAX_LENGTH:
        combined = combined[:_EVENT_SUMMARY_MAX_LENGTH] + "..."
    return combined


def _build_connpass_section_scripted(events: list[dict]) -> str:
    """connpass イベントリストをスクリプトで直接マークダウン化する（LLM 不使用）。

    取得したイベントデータをそのままフォーマットすることで、
    LLM による日時・URL・タイトルの誤生成を防ぐ。
    RSS 取得イベントは日時・場所が空の場合があるため、
    存在するフィールドのみを出力する。
    """
    if not events:
        return "### 📅 申し込み受付中のイベント\n\n現在取得できるイベント情報はありません。"

    blocks = []
    for event in events:
        title = event.get("title") or "（タイトルなし）"
        url = event.get("event_url", "")
        started_at = event.get("started_at", "")
        place = event.get("place", "") or event.get("address", "")
        catch = event.get("catch", "")
        description = event.get("description", "")
        accepted = event.get("accepted") or 0
        limit = event.get("limit") or 0
        series = event.get("series", "")

        block_lines = []
        if url:
            block_lines.append(f"**[{title}]({url})**")
        else:
            block_lines.append(f"**{title}**")

        if series:
            block_lines.append(f"**コミュニティ**: {series}")
        if started_at:
            block_lines.append(f"**開催日時**: {started_at}")
        if place:
            block_lines.append(f"**場所**: {place}")
        summary = _build_event_summary(catch, description)
        if summary:
            block_lines.append(f"**概要**: {summary}")
        if limit > 0:
            block_lines.append(f"**参加状況**: {accepted}/{limit}名")
        elif accepted > 0:
            block_lines.append(f"**参加状況**: {accepted}名（定員なし）")

        blocks.append("\n\n".join(block_lines))

    return "### 📅 申し込み受付中のイベント\n\n" + "\n\n---\n\n".join(blocks)


# マークダウンリンク [text](url) から URL を抽出するパターン
_MD_LINK_URL_RE = re.compile(rf'\[{_LINK_LABEL_RE}\]\((https?://[^)]+)\)')


def _load_previous_day_event_urls(target_date: str, updates_dir: str = "updates") -> set[str]:
    """前日の記事ファイルに含まれるリンク URL をすべて返す。

    前日の記事ファイルが存在しない場合や読み込みに失敗した場合は空集合を返す。
    マークダウンのリンク形式 [text](url) からすべての URL を抽出する。
    """
    target_dt = datetime.strptime(target_date, "%Y%m%d")
    prev_dt = target_dt - timedelta(days=1)
    prev_date_str = prev_dt.strftime("%Y%m%d")
    prev_path = os.path.join(updates_dir, f"{prev_date_str}.md")

    if not os.path.exists(prev_path):
        return set()

    try:
        with open(prev_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return set()

    return set(_MD_LINK_URL_RE.findall(content))


def _deprioritize_repeated_events(
    events: list[dict], prev_event_urls: set[str]
) -> list[dict]:
    """前日と重複するイベントをリストの末尾に移動する。

    events リスト内のイベントを、前日の記事に含まれていないイベント（優先）と
    含まれていたイベント（後回し）に分けて結合して返す。
    各グループ内では元のソート順（started_at 昇順）を維持する。
    """
    new_events = [e for e in events if e.get("event_url") not in prev_event_urls]
    repeated_events = [e for e in events if e.get("event_url") in prev_event_urls]
    return new_events + repeated_events


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
        "official_only": True,
        "system": (
            "あなたは Microsoft Azure の専門ライターです。"
            "提供された Azure ニュースはすべて Microsoft 公式ソース（Azure Release Communications および Azure Blog）から取得しています。"
            "提供されたデータのみを元に、正確で分かりやすい日本語の記事セクションを作成してください。"
        ),
        "instruction": (
            "以下の Azure 関連ニュースから 5〜6 個のトピックを選定し、マークダウン形式で出力してください。\n"
            "先頭に「## 1. Azure アップデート情報」を出力し、各トピックを次の形式で構成してください"
            "（各項目の間には必ず空行を入れること）。\n\n"
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。"
            "URL を自分で生成・変更・推測しないでください。コードブロックで囲まないこと。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。URL を自分で生成・変更・推測しないでください。コードブロックで囲まないこと。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。URL を自分で生成・変更・推測しないでください。コードブロックで囲まないこと。"
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
            "### <見出し>\n\n**要約**: ...\n\n**影響**: ...\n\n**リンク**: [タイトル](URL)\n\n"
            "見出し（###）自体はハイパーリンクにせず、リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、セクション末尾に締めの文章は入れないでください。"
            "リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。URL を自分で生成・変更・推測しないでください。コードブロックで囲まないこと。"
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
            "### <見出し>\n\n**要約**: ...\n\n**リンク**: [タイトル](URL)\n\n---\n\n"
            "見出し（###）自体はハイパーリンクにせず、リンクのみを [タイトル](URL) 形式で記載してください。"
            "また、サブセクション末尾に締めの文章は入れないでください。"
            "リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。URL を自分で生成・変更・推測しないでください。"
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


# _build_section_prompt は article_generator_shared の共通実装を使用する。
# dict/list 両型に対応しており、dict データのコミュニティセクションにも使える。
_build_section_prompt = _ags._build_section_prompt


def generate_section(
    client,
    model: str,
    section_def: dict,
    data: "dict | list",
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
        default_max_input=30_000,
        max_output_tokens=SECTION_MAX_OUTPUT_TOKENS,
        temperature=0.3,
    )


# コミュニティセクション：参加レポート部分の LLM instruction（ハイブリッド生成用）
_EVENT_REPORTS_LLM_INSTRUCTION = (
    "以下の参加レポートデータには Zenn・Qiita・はてなブックマーク などで公開された"
    "IT 系勉強会・コミュニティイベントの参加レポート、開催レポート、イベント告知記事が含まれます。\n"
    "IT 関連のもののみを選定し、先頭に「### 📝 参加レポート・イベント宣伝まとめ」を出力してください。\n"
    "その後、各記事を次の形式で構成してください"
    "（項目と項目の間には必ず空行と「---」区切りを入れること。最後の項目の後には「---」を入れないこと）。\n\n"
    "### <見出し>\n\n**要約**: ...\n\n**リンク**: [タイトル](URL)\n\n"
    "見出し（###）自体はハイパーリンクにせず、リンクのみを [タイトル](URL) 形式で記載してください。"
    "また、サブセクション末尾に締めの文章は入れないでください。"
    "リンクは必ず提供されたデータの url フィールドの値をそのまま使用してください。URL を自分で生成・変更・推測しないでください。"
    "IT 関連のレポートがない場合は「現在取得できる参加レポート情報はありません」と記載してください。"
    "コードブロックで囲まないこと。"
)


def _generate_community_section(
    client,
    model: str,
    section_def: dict,
    connpass_events: list[dict],
    event_reports: list[dict],
    since: "datetime | None" = None,
) -> str:
    """コミュニティイベントセクションをハイブリッド生成する。

    - connpass イベントリスト: スクリプトで直接マークダウン化（LLM 不使用）
      → 日時・URL・タイトルの誤生成を防ぐ
    - 参加レポート: LLM で要約・整形
      → 非構造化テキストの選択・要約は LLM に委ねる
    """
    header = section_def["header"]

    # connpass イベント部分: スクリプトで直接生成（LLM 不使用）
    connpass_md = _build_connpass_section_scripted(connpass_events)

    # 参加レポート部分: LLM で生成（データがある場合のみ）
    if event_reports:
        reports_section_def = {
            **section_def,
            "instruction": _EVENT_REPORTS_LLM_INSTRUCTION,
            "data_label": "コミュニティイベント参加レポート",
        }
        reports_md = generate_section(client, model, reports_section_def, event_reports, since=since)
        # LLM が先頭に ## ヘッダーを出力した場合は除去（後で追加するため）
        reports_md = re.sub(r'^## [^\n]+\n\n?', '', reports_md, count=1).strip()
        # LLM が末尾に「---」区切りを出力した場合は除去（複数連続・改行なしも対応）
        reports_md = re.sub(r'(?:\n?---[ \t]*)+\s*$', '', reports_md).rstrip()
    else:
        reports_md = "### 📝 参加レポート・イベント宣伝まとめ\n\n現在取得できる参加レポート情報はありません。"

    return f"{header}\n\n{connpass_md}\n\n{reports_md}"


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
    コミュニティセクションはハイブリッド生成（connpass スクリプト + レポート LLM）を使用する。
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
        if key == "community":
            # コミュニティセクションはハイブリッド生成:
            # connpass イベントはスクリプト、参加レポートは LLM
            section_text = _generate_community_section(
                client, model, section_def, connpass_events, event_reports, since=since
            )
        else:
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
    prev_event_urls = _load_previous_day_event_urls(target_date)
    connpass_events = fetch_connpass_events(target_date, prev_event_urls)
    print(f"  → 合計: {len(connpass_events)} 件")

    print("\n[コミュニティイベント参加レポート]")
    event_reports = _limit_articles(fetch_category("event_reports", since), "event_reports")
    print(f"  → 合計: {len(event_reports)} 件")

    # ソースデータ URL を収集（LLM 生成後のリンク検証に使用）
    source_urls = _collect_source_urls(
        azure_news, tech_news, business_news, sns_news, event_reports, connpass_events
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

    # ソース外リンクを検出・ログ出力（デバッグ・品質確認用）
    print("\nソース外リンクを確認中...")
    _log_unsourced_reference_links(article, source_urls)

    # ソース外リンクをソースデータの URL に置換する
    all_source_data = azure_news + tech_news + business_news + sns_news + event_reports
    article = _replace_unsourced_reference_links(article, all_source_data, source_urls)

    # リンクとコンテンツの内容近似性を検証し、不一致があれば修正する
    print("\nリンク内容近似性を確認中...")
    article = _verify_link_source_match(article, all_source_data)

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
    # 通常窓（since、直近 1〜2 日）で空になったセクションは、
    # 直近 1 か月（EXTENDED_LOOKBACK_DAYS）まで範囲を広げて再生成を試みる
    extended_since = target_dt - timedelta(days=EXTENDED_LOOKBACK_DAYS)
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
