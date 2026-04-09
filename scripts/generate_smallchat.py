"""
テクニカル雑談生成スクリプト

SNS を中心に IT 関連の話題を収集し、
GitHub Models (Claude Opus) / Azure OpenAI / OpenAI API でマークダウン記事を生成する。
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
        {"name": "Qiita GCP", "url": "https://qiita.com/tags/gcp/feed"},
        {"name": "Google News AWS", "url": "https://news.google.com/rss/search?q=AWS+Amazon+Web+Services&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News GCP", "url": "https://news.google.com/rss/search?q=Google+Cloud+Platform&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News OCI", "url": "https://news.google.com/rss/search?q=Oracle+Cloud+Infrastructure&hl=en&gl=US&ceid=US:en"},
        {"name": "Google News クラウド JP", "url": "https://news.google.com/rss/search?q=AWS+GCP+%E3%82%AF%E3%83%A9%E3%82%A6%E3%83%89&hl=ja&gl=JP&ceid=JP:ja"},
        {"name": "DevelopersIO AWS", "url": "https://dev.classmethod.jp/feed/"},
    ],
}

HTTP_HEADERS = {
    "User-Agent": "daily-updates-bot/1.0 (GitHub Actions; +https://github.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
}

MAX_ARTICLES_PER_CATEGORY = 10


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

    removed = len(unfixable_urls)
    replaced = len(replacement_urls)
    print(f"  リンク検証完了: 代替リンク={replaced} 件, トピック除去={removed} 件")
    return result


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


# --- LLM クライアント -----------------------------------------------------------


def create_llm_client() -> tuple:
    """環境変数に応じて GitHub Models / Azure OpenAI / OpenAI クライアントを生成する。"""
    # 優先順位: GitHub Models (GITHUB_TOKEN) → Azure OpenAI → OpenAI
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=github_token,
        )
        return client, "claude-opus-4"

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

    raise RuntimeError(
        "LLM の認証情報が見つかりません。"
        "GITHUB_TOKEN, OPENAI_API_KEY, または AZURE_OPENAI_ENDPOINT を設定してください。"
    )


# --- 記事生成 -------------------------------------------------------------------

SYSTEM_PROMPT = """\
あなたは IT 分野のテクニカルライターです。
SNS やニュースソースから収集した情報を元に、IT エンジニア向けのカジュアルなテクニカル雑談記事を作成してください。

## ルール
- 読むのに約5分かかる分量で書いてください（2000〜3000文字程度）。
- 各トピックは「見出し」「要約」「影響」「参考リンク」の4項目で構成してください。
- 各項目（**要約**、**影響**、**参考リンク**）の間には必ず空行を入れてください。
- 要約は簡潔かつ具体的に。影響はエンジニアや開発者にとっての意味を記載してください。
- 参考リンクは提供されたソースの URL をそのまま使用してください。
- 情報が不足している場合は無理に水増しせず、取得できた範囲で記載してください。
- マークダウン形式で出力してください。コードブロックで囲まないでください。
"""


def build_user_prompt(
    target_date: str,
    slot: str,
    microsoft_news: list[dict],
    ai_news: list[dict],
    azure_news: list[dict],
    security_news: list[dict],
    cloud_news: list[dict],
) -> str:
    formatted_date = f"{target_date[:4]}/{target_date[4:6]}/{target_date[6:]}"
    slot_label = "午前" if slot == "am" else "午後"
    return f"""\
以下のニュースソースを元に、{formatted_date} {slot_label}のテクニカル雑談記事を作成してください。
日本語・英語の両方のソースが含まれていますが、記事はすべて日本語で書いてください。

出力フォーマット（各項目の間には必ず空行を入れること。コードブロックで囲まず、マークダウンをそのまま出力すること）:

# {formatted_date} テクニカル雑談（{slot_label}）

## 1. Microsoft

(最大3つ。各トピックは見出し・要約・影響・参考リンクで構成)

## 2. AI

(最大3つ。各トピックは見出し・要約・影響・参考リンクで構成)

## 3. Azure

(最大3つ。各トピックは見出し・要約・影響・参考リンクで構成)

## 4. クラウド（AWS / GCP / OCI）

(最大3つ。Azure以外のクラウドサービス（AWS、GCP、OCI等）のトレンド。各トピックは見出し・要約・影響・参考リンクで構成)

## 5. セキュリティ

(最大3つ。各トピックは見出し・要約・影響・参考リンクで構成)

---

### Microsoft 関連
{json.dumps(microsoft_news, ensure_ascii=False, indent=2)}

### AI 関連
{json.dumps(ai_news, ensure_ascii=False, indent=2)}

### Azure 関連
{json.dumps(azure_news, ensure_ascii=False, indent=2)}

### クラウド（AWS / GCP / OCI）関連
{json.dumps(cloud_news, ensure_ascii=False, indent=2)}

### セキュリティ関連
{json.dumps(security_news, ensure_ascii=False, indent=2)}
"""


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
) -> str:
    MAX_INPUT_CHARS = 15_000 * 2.5

    news_lists = [microsoft_news, ai_news, azure_news, security_news, cloud_news]
    user_prompt = build_user_prompt(
        target_date, slot, microsoft_news, ai_news, azure_news, security_news, cloud_news
    )

    while len(user_prompt) > MAX_INPUT_CHARS:
        trimmed = False
        for nl in news_lists:
            if len(nl) > 3:
                nl.pop()
                trimmed = True
        if not trimmed:
            break
        user_prompt = build_user_prompt(
            target_date, slot, microsoft_news, ai_news, azure_news, security_news, cloud_news
        )

    if len(user_prompt) > MAX_INPUT_CHARS:
        print("  ⚠ プロンプトが大きいため description を除去します")
        for nl in news_lists:
            for article in nl:
                article["description"] = ""
        user_prompt = build_user_prompt(
            target_date, slot, microsoft_news, ai_news, azure_news, security_news, cloud_news
        )

    print(f"  プロンプトサイズ: 約 {len(user_prompt):,} 文字")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=4096,
    )
    return response.choices[0].message.content


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

    print("\n記事を生成中...")
    client, model = create_llm_client()
    article = generate_article(
        client, model, target_date, slot, microsoft_news, ai_news, azure_news, security_news, cloud_news
    )

    print("\nリンクを検証中...")
    article = validate_links(article)

    output_dir = "smallchat"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{target_date}_{slot}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(article + "\n")

    print(f"生成完了: {output_path}")


if __name__ == "__main__":
    main()
