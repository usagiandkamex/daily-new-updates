"""
デイリーアップデート生成スクリプト

複数の RSS/Atom フィードで最新ニュースを取得し、
GitHub Models / OpenAI / Azure OpenAI API でマークダウン記事を生成する。
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


# カテゴリ別の記事数上限（プロンプトサイズ制御用）
MAX_ARTICLES = {
    "azure": 20,
    "tech": 30,
    "business": 30,
    "sns": 20,
}


def _limit_articles(articles: list[dict], category: str) -> list[dict]:
    """記事リストをカテゴリ上限に制限する。"""
    limit = MAX_ARTICLES.get(category, 10)
    if len(articles) > limit:
        print(f"  ※ {len(articles)} 件 → {limit} 件に制限")
    return articles[:limit]


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
- 読むのに約8分かかる分量で書いてください（4000〜5000文字程度）。
- 各セクションにつき **必ず5〜6個** のトピックを選定してください。ソースが少ない場合のみ減らしてよいですが、3個以下にならないようにしてください。
- 「ニュースで話題のテーマ」には IT・テクノロジー関連のトピックのみを入れてください。ビジネスニュースの中に IT 関連のものがあれば、それもここに含めてください。
- 「ビジネスホットトピック」には IT 以外のトピックのみを入れてください。世界情勢、経済・金融、政治、社会問題、産業動向など、IT 以外のビジネス話題を選定してください。
- 各トピックは「見出し」「要約」「影響」「参考リンク」の4項目で構成してください。
- 各項目（**要約**、**影響**、**参考リンク**）の間には必ず空行を入れてください。
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
技術系ニュースとビジネスニュースの両方から IT・テクノロジー関連のトピックは「ニュースで話題のテーマ」に活用してください。
SNS/トレンド情報は「SNSで話題のテーマ」に活用してください。
「ビジネスホットトピック」には IT 以外のトピック（世界情勢、経済・金融、政治、社会問題、産業動向など）のみを入れてください。IT企業の決算やAI半導体の話題など IT 関連のビジネスニュースは「ニュースで話題のテーマ」に入れてください。

出力フォーマット（各項目の間には必ず空行を入れること。コードブロックで囲まず、マークダウンをそのまま出力すること）:

# {formatted_date} デイリーアップデート

## 1. Azure アップデート情報

### <見出し>

**要約**: ...

**影響**: ...

**参考リンク**: [タイトル](URL)

(複数トピックがあれば繰り返し。5〜6個選定すること)

## 2. ニュースで話題のテーマ

(5〜6個。IT・テクノロジー関連のニュースから選定。技術系・ビジネス系両方のソースからIT関連を集める。各トピックは見出し・要約・影響・参考リンクで構成)

## 3. SNSで話題のテーマ

(5〜6個。はてブ・ Reddit 等のトレンドから選定。各トピックは見出し・要約・影響・参考リンクで構成)

## 4. ビジネスホットトピック

(5〜6個。IT以外のトピックのみ。世界情勢、経済・金融、政治、社会問題、産業動向など。各トピックは見出し・要約・影響・参考リンクで構成)

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
    # プロンプトサイズの安全チェック (128,000 トークン制限 - 8,192 出力 - 約 600 システム)
    # 概算: 日英混在で 1 トークン ≈ 2.5 文字
    MAX_INPUT_CHARS = 20_000 * 2.5  # ≈ 50,000 文字

    news_lists = [azure_news, tech_news, business_news, sns_news]
    user_prompt = build_user_prompt(
        target_date, azure_news, tech_news, business_news, sns_news
    )

    # プロンプトが大きすぎる場合、各カテゴリから均等に記事を削る
    while len(user_prompt) > MAX_INPUT_CHARS:
        trimmed = False
        for nl in news_lists:
            if len(nl) > 3:
                nl.pop()
                trimmed = True
        if not trimmed:
            break
        user_prompt = build_user_prompt(
            target_date, azure_news, tech_news, business_news, sns_news
        )

    if len(user_prompt) > MAX_INPUT_CHARS:
        print(f"  ⚠ プロンプトが大きいため description を除去します")
        for nl in news_lists:
            for article in nl:
                article["description"] = ""
        user_prompt = build_user_prompt(
            target_date, azure_news, tech_news, business_news, sns_news
        )

    print(f"  プロンプトサイズ: 約 {len(user_prompt):,} 文字")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=8192,
    )
    return response.choices[0].message.content


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

    print("\n記事を生成中...")
    client, model = create_llm_client()
    article = generate_article(
        client, model, target_date, azure_news, tech_news, business_news, sns_news
    )

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
