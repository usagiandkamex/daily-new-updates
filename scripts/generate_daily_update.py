"""
デイリーアップデート生成スクリプト

複数の RSS/Atom フィードで最新ニュースを取得し、
GitHub Models / OpenAI / Azure OpenAI API でマークダウン記事を生成する。
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from openai import AzureOpenAI, OpenAI

JST = timezone(timedelta(hours=9))

# --- ニュースソース定義 ---------------------------------------------------------------

FEEDS = {
    # --- Azure ---
    "azure": [
        {"name": "Azure Updates", "url": "https://azure.microsoft.com/ja-jp/updates/feed/"},
    ],
    # --- 技術系 (日本語) ---
    "tech_ja": [
        {"name": "ITmedia NEWS", "url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"},
        {"name": "GIGAZINE", "url": "https://gigazine.net/news/rss_2.0/"},
        {"name": "Publickey", "url": "https://www.publickey1.jp/atom.xml"},
        {"name": "クラウド Watch", "url": "https://cloud.watch.impress.co.jp/data/rss/1.0/cw/feed.rdf"},
        {"name": "Zenn トレンド", "url": "https://zenn.dev/feed"},
    ],
    # --- 技術系 (英語) ---
    "tech_en": [
        {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
        {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
        {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index"},
        {"name": "Hacker News (Best)", "url": "https://hnrss.org/best"},
        {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
    ],
    # --- ビジネス系 (日本語) ---
    "business_ja": [
        {"name": "NHK ビジネス", "url": "https://www.nhk.or.jp/rss/news/cat4.xml"},
        {"name": "東洋経済オンライン", "url": "https://toyokeizai.net/list/feed/rss"},
        {"name": "ITmedia ビジネス", "url": "https://rss.itmedia.co.jp/rss/2.0/business_articles.xml"},
        {"name": "Google News 経済", "url": "https://news.google.com/rss/search?q=%E7%B5%8C%E6%B8%88+%E3%83%93%E3%82%B8%E3%83%8D%E3%82%B9&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "Google News IT企業", "url": "https://news.google.com/rss/search?q=IT%E4%BC%81%E6%A5%AD+%E3%82%B9%E3%82%BF%E3%83%BC%E3%83%88%E3%82%A2%E3%83%83%E3%83%97&hl=ja&gl=JP&ceid=JP:ja"},
    ],
    # --- ビジネス系 (英語) ---
    "business_en": [
        {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
        {"name": "CNBC Tech", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"},
        {"name": "Google News (Reuters Business)", "url": "https://news.google.com/rss/search?q=business+technology+site:reuters.com&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (Bloomberg Tech)", "url": "https://news.google.com/rss/search?q=technology+site:bloomberg.com&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News (Financial Times)", "url": "https://news.google.com/rss/search?q=technology+business+site:ft.com&hl=en&gl=US&ceid=US:en"},
    ],
    # --- SNS / トレンド ---
    "sns": [
        {"name": "はてなブックマーク IT", "url": "https://b.hatena.ne.jp/hotentry/it.rss"},
        {"name": "Reddit Technology", "url": "https://www.reddit.com/r/technology/.rss"},
        {"name": "Reddit Programming", "url": "https://www.reddit.com/r/programming/.rss"},
    ],
}

HTTP_HEADERS = {
    "User-Agent": "daily-updates-bot/1.0 (GitHub Actions; +https://github.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
}


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

        articles.append(
            {
                "title": entry.get("title", "").strip(),
                "description": entry.get("summary", "").strip()[:300],
                "url": entry.get("link", ""),
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
            items = _fetch_feed(source["url"], since, max_items=10)
            for item in items:
                item["source"] = source["name"]
            all_articles.extend(items)
            print(f"    {source['name']}: {len(items)} 件")
        except Exception as e:
            print(f"    {source['name']}: 取得失敗 ({e})")
    return all_articles


# --- LLM クライアント -----------------------------------------------------------


def create_llm_client() -> tuple:
    """環境変数に応じて GitHub Models / OpenAI / Azure OpenAI クライアントを生成する。"""
    # 優先順位: Azure OpenAI → OpenAI → GitHub Models (GITHUB_TOKEN)
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if azure_endpoint:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version="2024-12-01-preview",
        )
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        return client, deployment

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if openai_api_key:
        client = OpenAI(api_key=openai_api_key)
        return client, "gpt-4o"

    # GitHub Models (GITHUB_TOKEN を使用)
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=github_token,
        )
        return client, "gpt-4o"

    raise RuntimeError(
        "LLM の認証情報が見つかりません。"
        "GITHUB_TOKEN, OPENAI_API_KEY, または AZURE_OPENAI_ENDPOINT を設定してください。"
    )


# --- 記事生成 -------------------------------------------------------------------

SYSTEM_PROMPT = """\
あなたは IT・ビジネスニュースの専門ライターです。
提供されたニュースソースを元に、正確で分かりやすい日本語のデイリーアップデート記事を作成してください。

## ルール
- 読むのに約5分かかる分量で書いてください（2000〜3000文字程度）。
- 各トピックは「見出し」「要約」「影響」「参考リンク」の4項目で構成してください。
- 要約は簡潔かつ具体的に。影響はビジネスや開発者にとっての意味を記載してください。
- 参考リンクは提供されたソースの URL をそのまま使用してください。
- 情報が不足している場合は無理に水増しせず、取得できた範囲で記載してください。
- マークダウン形式で出力してください。
"""


def build_user_prompt(
    target_date: str,
    azure_news: list[dict],
    tech_news: list[dict],
    business_news: list[dict],
    sns_news: list[dict],
) -> str:
    formatted_date = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:]}"
    return f"""\
以下のニュースソースを元に、{formatted_date} のデイリーアップデート記事を作成してください。
日本語・英語の両方のソースが含まれていますが、記事はすべて日本語で書いてください。
技術系ニュースは「ニュースで話題のテーマ」に、SNS/トレンド情報は「SNSで話題のテーマ」に活用してください。

出力フォーマット:
```
# {formatted_date} デイリーアップデート

## 1. Azure アップデート情報

### <見出し>
**要約**: ...
**影響**: ...
**参考リンク**: [タイトル](URL)

(複数トピックがあれば繰り返し)

## 2. ニュースで話題のテーマ

(最大3つ。技術系ニュースソースから選定。各トピックは見出し・要約・影響・参考リンクで構成)

## 3. SNSで話題のテーマ

(最大3つ。はてブ・ Reddit 等のトレンドから選定。各トピックは見出し・要約・影響・参考リンクで構成)

## 4. ビジネスホットトピック

(最大3つ。各トピックは見出し・要約・影響・参考リンクで構成)
```

---

### Azure 関連ニュース
{json.dumps(azure_news, ensure_ascii=False, indent=2)}

### 技術系ニュース（日本語 + 英語ソース）
{json.dumps(tech_news, ensure_ascii=False, indent=2)}

### ビジネスニュース（日本語 + 英語ソース）
{json.dumps(business_news, ensure_ascii=False, indent=2)}

### SNS / トレンド（はてブ・ Reddit）
{json.dumps(sns_news, ensure_ascii=False, indent=2)}
"""


def generate_article(
    client,
    model: str,
    target_date: str,
    azure_news: list[dict],
    tech_news: list[dict],
    business_news: list[dict],
    sns_news: list[dict],
) -> str:
    user_prompt = build_user_prompt(
        target_date, azure_news, tech_news, business_news, sns_news
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return response.choices[0].message.content


# --- メイン処理 -----------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_daily_update.py YYYYMMDD")
        sys.exit(1)

    target_date = sys.argv[1]
    # 前日 8:30 JST 以降の記事を対象とする
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=JST)
    since = target_dt - timedelta(days=1) + timedelta(hours=8, minutes=30)

    print(f"対象日: {target_date}")
    print(f"収集期間: {since.isoformat()} 以降")
    print("ニュースを取得中...")

    print("\n[Azure]")
    azure_news = fetch_category("azure", since)
    print(f"  → 合計: {len(azure_news)} 件")

    print("\n[技術系 日本語]")
    tech_ja = fetch_category("tech_ja", since)
    print(f"  → 合計: {len(tech_ja)} 件")

    print("\n[技術系 英語]")
    tech_en = fetch_category("tech_en", since)
    print(f"  → 合計: {len(tech_en)} 件")

    tech_news = tech_ja + tech_en

    print("\n[ビジネス系 日本語]")
    biz_ja = fetch_category("business_ja", since)
    print(f"  → 合計: {len(biz_ja)} 件")

    print("\n[ビジネス系 英語]")
    biz_en = fetch_category("business_en", since)
    print(f"  → 合計: {len(biz_en)} 件")

    business_news = biz_ja + biz_en

    print("\n[SNS / トレンド]")
    sns_news = fetch_category("sns", since)
    print(f"  → 合計: {len(sns_news)} 件")

    print("\n記事を生成中...")
    client, model = create_llm_client()
    article = generate_article(
        client, model, target_date, azure_news, tech_news, business_news, sns_news
    )

    output_path = f"{target_date}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
