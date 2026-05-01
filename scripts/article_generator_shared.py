"""
デイリーアップデート・テクニカル雑談の共通生成ユーティリティ

generate_daily_update.py と generate_smallchat.py の両ワークフローで
共有するクラスおよび関数を提供する。共通機能をここで一元管理することで、
改善や修正を両ワークフローに同時に反映させることができる。
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse, urlunparse

import feedparser
import requests
from googlenewsdecoder import new_decoderv1
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

# 日本標準時
JST = timezone(timedelta(hours=9))

# LLM 呼び出しのリトライ設定
# 一時的なエラー（レート制限・接続エラー・サーバーエラー）に対して指数バックオフでリトライする
_LLM_MAX_RETRIES = 3
_LLM_RETRY_BASE_WAIT = 5  # 秒（2^n 倍で増加: 5, 10 秒）

# HTTP リクエスト共通ヘッダー
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

# URL 正規化時に除去するトラッキング専用クエリパラメータのパターン。
# utm_* は Google Analytics 標準、fbclid/gclid/msclkid は各広告プラットフォームのクリック追跡用。
# id= などのコンテンツ識別パラメータはここに含めず、正規化後も保持する。
_TRACKING_PARAM_RE = re.compile(r'^(utm_|fbclid$|gclid$|msclkid$)', re.IGNORECASE)

# タイトル正規化用プリコンパイル正規表現（SourceUrlTracker の複数メソッドで共用）。
# [In preview] などの角括弧付きプレフィックスと Azure 系ステータス語を除去して
# 単語レベルの重複スコアリングに使う共通正規化パターン。
_TITLE_BRACKET_RE = re.compile(r'\[[^\]]+\]')
_TITLE_STATUS_RE = re.compile(
    r'\b(?:Public Preview|Generally Available|Preview|GA|'
    r'Retirement|Retired?|Launched|In preview)\b\s*:?\s*',
    re.IGNORECASE,
)

# 代替 URL 検索でネットワーク障害が発生した場合を示すセンチネル。
# None（検索結果なし）と区別するために使用する。
class _SearchUnavailableSentinel:
    """検索サービス自体が利用不可の場合を示すセンチネル型。"""
    pass

_SEARCH_UNAVAILABLE = _SearchUnavailableSentinel()


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


def _to_azure_ja_url(url: str) -> str:
    """Azure アップデートの URL を日本語ロケール付き（/ja-jp/updates）形式に変換する。

    Azure Release Communications RSS フィードが提供する URL は
    ロケールなし（/updates?id=NNNN）または英語ロケール（/en-us/updates?id=NNNN）だが、
    日本語ユーザーに適した /ja-jp/updates?id=NNNN 形式に変換して提供する。
    非 Azure URL、または /updates 以外のパス（/blog/ 等）はそのまま返す。
    """
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname != "azure.microsoft.com":
        return url
    # /updates または /{locale}/updates パスをロケール付きに変換
    # ロケールプレフィックスのみを除去し、/updates 以降のパスはすべて保持する
    m = re.match(r'^/[a-z]{2}-[a-z]{2}(?=/updates(?:/|$))', parsed.path, re.IGNORECASE)
    if m:
        path_without_locale = parsed.path[m.end():]
    elif re.match(r'^/updates(?:/|$)', parsed.path, re.IGNORECASE):
        path_without_locale = parsed.path
    else:
        return url
    new_path = "/ja-jp" + path_without_locale
    return urlunparse((parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))


# --- リンク検証 ---------------------------------------------------------------


def _validate_url(url: str) -> tuple[bool, str]:
    """単一 URL を検証し、(OK, 理由) を返す。

    接続エラー・タイムアウト等のネットワーク障害時はソフトフェイル（有効とみなす）。
    URL の有効性が不明な場合にトピックを誤って除去しないようにするための措置。
    """
    try:
        resp = requests.head(
            url,
            headers={"User-Agent": HTTP_HEADERS["User-Agent"]},
            timeout=5,
            allow_redirects=True,
        )
        # HEAD が 405 の場合は GET でリトライ
        if resp.status_code == 405:
            resp = requests.get(
                url,
                headers={"User-Agent": HTTP_HEADERS["User-Agent"]},
                timeout=5,
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
    except requests.exceptions.SSLError as e:
        # SSL 証明書エラー等は恒久的エラーとして無効とみなす
        return False, f"接続エラー ({e.__class__.__name__})"
    except (requests.ConnectionError, requests.Timeout) as e:
        # 一時的なネットワーク障害・タイムアウト: URL の有効性が不明なためソフトフェイル（有効とみなす）
        print(f"    URL 検証スキップ（接続エラー）: {url[:80]} — {e.__class__.__name__}")
        return True, f"検証スキップ ({e.__class__.__name__})"
    except requests.RequestException as e:
        # SSL エラー・リダイレクトループ・無効な URL 等の恒久的エラーは無効とみなす
        return False, f"接続エラー ({e.__class__.__name__})"


def _normalize_domain(parsed) -> str:
    """urlparse 結果のホスト名を小文字化・末尾ドット除去して返す。

    netloc はポート番号を含む場合があり大小文字も保持されるため、
    hostname（Python が小文字化済み）を優先して使用する。
    ドメイン集合 source_domains への追加と link_domain の取得の両方で
    同じ正規化を適用することで、大小文字やポート付きホストによる誤検知を防ぐ。
    """
    hostname = parsed.hostname
    if hostname:
        return hostname.lower().rstrip(".")
    return parsed.netloc.lower().rstrip(".")


# HTTP ページタイトルフェッチを環境変数で無効化できる（デフォルト有効）。
# DAILY_NEWS_FETCH_PAGE_TITLE=0 に設定するとステップ④をスキップする。
_FETCH_PAGE_TITLE_ENABLED = os.environ.get("DAILY_NEWS_FETCH_PAGE_TITLE", "1") != "0"


def _fetch_page_title(url: str) -> str:
    """HTTP GET でリンク先ページのタイトルを取得する。

    og:title メタタグを優先し、なければ <title> タグを使用する。
    先頭 8 KB のみ読み込むことで大容量ページのダウンロードを避ける。
    接続エラー・タイムアウト・HTTP エラー等のネットワーク障害時は
    空文字列を返す（ソフトフェイル）。全セクション（Azure 含む）に
    対して共通して使用できる汎用実装。
    """
    resp = None
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": HTTP_HEADERS["User-Agent"]},
            timeout=10,
            allow_redirects=True,
            stream=True,
        )
        if not resp.ok:
            return ""
        # Content-Type が HTML でない場合はページタイトルを持たないためスキップ
        content_type = resp.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            return ""
        # <title> と og:title はほぼ先頭にあるため先頭 8 KB のみ取得する
        content = b""
        for chunk in resp.iter_content(chunk_size=8192):
            content += chunk
            if len(content) >= 8192:
                break
        html_head = content.decode("utf-8", errors="ignore")
        # og:title を優先（属性順序・等号前後スペースに依存しないよう2パターンを検索）
        m = re.search(
            r'<meta[^>]+property\s*=\s*["\']og:title["\'][^>]+content\s*=\s*["\']([^"\'<]+)',
            html_head, re.IGNORECASE,
        )
        if not m:
            m = re.search(
                r'<meta[^>]+content\s*=\s*["\']([^"\'<]+)["\'][^>]+property\s*=\s*["\']og:title["\']',
                html_head, re.IGNORECASE,
            )
        if m:
            import html as html_mod
            return html_mod.unescape(m.group(1).strip())
        # og:title がなければ <title> タグを使用
        m = re.search(r'<title[^>]*>([^<]+)</title>', html_head, re.IGNORECASE)
        if m:
            import html as html_mod
            return html_mod.unescape(m.group(1).strip())
    except (requests.ConnectionError, requests.Timeout):
        pass
    except requests.RequestException:
        pass
    except Exception as e:
        # 想定外のエラー（HTML パース失敗・実装バグ等）をログしてデバッグを支援（ソフトフェイルは維持）
        print(
            f"  ⚠ _fetch_page_title: 予期しないエラー"
            f" ({type(e).__name__}: {e}) url={url!r}"
        )
    finally:
        if resp is not None:
            resp.close()
    return ""


def _search_alternative_url(query: str) -> "str | None | _SearchUnavailableSentinel":
    """Google News RSS で代替記事を検索し、最初の有効な URL を返す。

    Returns:
        代替記事の URL 文字列（見つかった場合）、
        検索結果が見つからない場合は None、
        ネットワーク障害など検索サービス自体が利用不可の場合は _SEARCH_UNAVAILABLE センチネル。
    """
    search_url = (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    )
    try:
        resp = requests.get(
            search_url,
            headers=HTTP_HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            if 500 <= resp.status_code < 600:
                print(f"    代替検索失敗（検索サービス障害）: HTTP {resp.status_code}")
                return _SEARCH_UNAVAILABLE
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
    except requests.RequestException as e:
        # ネットワーク障害・タイムアウト: 検索サービス自体が利用不可
        print(f"    代替検索失敗（ネットワーク障害）: {e.__class__.__name__}")
        return _SEARCH_UNAVAILABLE
    except Exception as e:
        print(f"    代替検索失敗: {e}")
    return None


def _format_bare_reference_links(markdown: str) -> str:
    """**リンク**: の後に裸の URL または URL をラベルにしたリンクがある場合、
    直近の ### 見出しをラベルにしたハイパーリンクへ変換する。"""
    lines = markdown.splitlines()
    current_heading = ""
    result = []
    for line in lines:
        heading_match = re.match(r'^###\s+(.+)', line)
        if heading_match:
            current_heading = heading_match.group(1).strip()

        # 裸の URL: **リンク**: https://...
        ref_bare = re.match(r'^(\*\*リンク\*\*:\s*)(https?://\S+)\s*$', line)
        # URL をラベルにしたリンク: **リンク**: [https://...](https://...)
        ref_url_label = re.match(
            r'^(\*\*リンク\*\*:\s*)\[(https?://[^\]]+)\]\((https?://[^)]+)\)\s*$', line
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
        if alt is _SEARCH_UNAVAILABLE:
            # 検索サービス自体が利用不可のためスキップ（元リンクを保持）
            print(f"       → 代替検索サービス障害、スキップ（元リンクを保持）")
        elif alt:
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
      2. 各トピックに **要約** と **リンク** が含まれること
      3. **リンク** が [タイトル](URL) 形式であること
      4. セクション末尾に不要な締め文がないこと
      5. 連続 --- セパレータや孤立セパレータがないこと
    修正可能な問題は自動修正し、全ての検出事項をログ出力する。
    コミュニティイベントセクション（「コミュニティ」を含む見出し）の
    箇条書きサブセクション（📅・📝 で始まる見出し）は要約・リンクのチェックを省略する。
    """
    lines = markdown.split('\n')
    fixed_lines: list[str] = []
    issues: list[str] = []

    # --- 1. 見出しのハイパーリンク解除 ---
    # ### [タイトル](URL) 形式のリンク見出し、および
    # ### [タイトル] のように見出し全体が角括弧で囲まれているケースの両方を解除する。
    # ただし「### [In preview] New Feature」のように見出しの一部だけが角括弧で
    # 囲まれている場合は意味があるため変更しない。
    _heading_link_re = re.compile(
        r'^(###\s+)\[(' + _LINK_LABEL_RE + r')\]\(https?://[^)]+\)\s*$'
    )
    _heading_bracket_re = re.compile(
        r'^(###\s+)\[(' + _LINK_LABEL_RE + r')\]\s*$'
    )
    for line in lines:
        m = _heading_link_re.match(line)
        if m:
            label = m.group(2).strip()
            fixed_line = f"{m.group(1)}{label}"
            fixed_lines.append(fixed_line)
            issues.append(f"見出しリンク修正: '{label}'")
            continue
        m = _heading_bracket_re.match(line)
        if m:
            label = m.group(2).strip()
            fixed_line = f"{m.group(1)}{label}"
            fixed_lines.append(fixed_line)
            issues.append(f"見出し角括弧除去: '{label}'")
            continue
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

            # **リンク** チェック — コミュニティ箇条書きサブセクションは除外
            if not is_community_list and '**リンク**' not in topic_block:
                issues.append(f"リンクなし: [{section_name}] {topic_title}")
            elif not is_community_list:
                # リンクの形式チェック: [text](URL) が含まれるか
                ref_line_re = re.compile(r'\*\*リンク\*\*:\s*(.*)', re.MULTILINE)
                ref_match = ref_line_re.search(topic_block)
                if ref_match:
                    ref_value = ref_match.group(1).strip()
                    link_re = re.compile(rf'\[{_LINK_LABEL_RE}\]\(https?://[^)]+\)')
                    if not link_re.search(ref_value):
                        issues.append(f"リンク形式不正: [{section_name}] {topic_title}")

    # --- 3. セクション末尾の締め文検出 ---
    # 最後のトピックの **リンク** (または ---) 以降に余分なテキストがないかチェック
    _closing_re = re.compile(
        r'(\*\*リンク\*\*:\s*\[' + _LINK_LABEL_RE + r'\]\(https?://[^)]+\))'
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


# --- フィード取得 -----------------------------------------------------------------


def _fetch_feed(
    url: str,
    since: datetime,
    max_items: int = 10,
    max_age_days: "int | None" = None,
) -> list[dict]:
    """単一の RSS/Atom フィードを取得し、since 以降の記事を返す。

    max_age_days が指定された場合、その日数より古い記事を絶対上限として除外する。
    日付のない記事は新鮮さを確認できないため常に除外する。
    """
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    max_age_cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
        if max_age_days is not None
        else None
    )

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

        # max_age_days が指定された場合、絶対上限として古すぎる記事を除外する
        if max_age_cutoff is not None and pub_date < max_age_cutoff:
            continue

        article_url = _resolve_google_news_url(entry.get("link", ""))
        article_url = _to_azure_ja_url(article_url)
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


def fetch_category(
    feeds: dict,
    category: str,
    since: datetime,
    max_items_per_feed: int = 10,
    max_age_days: "int | None" = None,
    caps: "dict[str, int] | None" = None,
    default_cap: "int | None" = None,
) -> list[dict]:
    """カテゴリに属する全フィードから記事を収集する。

    feeds: カテゴリ名 → フィードリストのマッピング（スクリプト固有）
    caps: カテゴリごとの記事数上限オーバーライド
    default_cap: caps に一致するエントリがない場合の上限（None = 制限なし）
    """
    all_articles = []
    for source in feeds.get(category, []):
        try:
            items = _fetch_feed(
                source["url"], since,
                max_items=max_items_per_feed,
                max_age_days=max_age_days,
            )
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

    if default_cap is not None or caps is not None:
        cap = (caps or {}).get(category, default_cap)
        if cap is not None and len(deduped) > cap:
            print(f"  ※ {len(deduped)} 件 → {cap} 件に制限")
            deduped = deduped[:cap]

    return deduped


# --- LLM セクション生成 -----------------------------------------------------------


def _build_section_prompt(
    section_def: dict,
    data: "dict | list",
    since: "datetime | None" = None,
) -> str:
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
    data: "dict | list",
    since: "datetime | None" = None,
    *,
    max_input_chars: "dict[str, int] | None" = None,
    default_max_input: int = 20_000,
    max_output_tokens: int = 3000,
    temperature: float = 0.3,
) -> str:
    """1 セクション分の記事を LLM で生成する。

    max_input_chars: セクションキー → 入力文字数上限のマッピング（スクリプト固有）
    default_max_input: max_input_chars に一致するエントリがない場合のデフォルト
    max_output_tokens: LLM の出力トークン上限
    temperature: LLM の temperature パラメータ
    """
    key = section_def["key"]
    max_input = (max_input_chars or {}).get(key, default_max_input)

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

    # 一時的なエラーに対して指数バックオフでリトライする
    _TRANSIENT_ERRORS = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)
    last_error: Exception | None = None
    for attempt in range(_LLM_MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": section_def["system"]},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_output_tokens,
            )
            return response.choices[0].message.content.strip()
        except _TRANSIENT_ERRORS as e:
            last_error = e
            if attempt < _LLM_MAX_RETRIES - 1:
                wait = _LLM_RETRY_BASE_WAIT * (2 ** attempt)
                print(
                    f"    ⚠ LLM 呼び出し失敗 (試行 {attempt + 1}/{_LLM_MAX_RETRIES})、"
                    f"{wait} 秒後にリトライ... ({e})"
                )
                time.sleep(wait)
    # ここに到達するのは全リトライが一時的エラーで失敗した場合のみ。
    # _LLM_MAX_RETRIES < 1 の設定不正で last_error が未設定になり得るため、明示的に検出する。
    if last_error is None:
        raise RuntimeError("_LLM_MAX_RETRIES must be at least 1.")
    raise last_error


class SourceUrlTracker:
    """フィード取得したソース URL を管理し、LLM 生成後のリンク検証に使用するクラス。

    デイリーアップデート・テクニカル雑談の両ワークフローで共通して使用する。
    LLM が提供されたソースデータ外の URL を生成した可能性がある箇所を可視化し、
    デバッグや品質改善に役立てる。
    """

    @staticmethod
    def _normalize_url(url: str) -> str:
        """URL を正規化してトラッキングパラメータとフラグメントを除去する。

        utm_* などのトラッキング専用パラメータと #section のフラグメントを除去する。
        id= などのコンテンツ識別パラメータは保持する。これにより、同一記事を指す
        URL のバリエーション（utm 追跡付き等）を同一視しつつ、?id= などで区別される
        異なる記事は別の URL として扱う（例: Azure アップデートの ?id=NNNN）。
        パラメータはキー昇順でソートし、比較時の順序差異を吸収する。

        Azure アップデートの URL（azure.microsoft.com/{locale}/updates?id=...）は
        ロケールプレフィックスを除去して /updates?id=... に正規化する。
        RSS フィードが提供する URL はロケールなし（/updates?id=...）のため、
        LLM がロケール付き URL（例: /ja-jp/updates?id=...）を生成した場合でも
        クエリパラメータ id= で同一記事として識別できるようにする。
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        # Azure アップデートページのロケールプレフィックスを除去する
        # 例: https://azure.microsoft.com/ja-jp/updates?id=NNNN
        #   → https://azure.microsoft.com/updates?id=NNNN
        # /updates 以降のパスは保持する
        path = parsed.path
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname == "azure.microsoft.com":
            m = re.match(r'^/[a-z]{2}-[a-z]{2}(?=/updates(?:/|$))', path, re.IGNORECASE)
            if m:
                path = path[m.end():]
        if not parsed.query:
            return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
        # トラッキングパラメータを除去し、コンテンツ識別パラメータは保持する
        params = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {k: v for k, v in params.items() if not _TRACKING_PARAM_RE.match(k)}
        if filtered:
            new_query = urlencode(sorted(filtered.items()), doseq=True)
            return urlunparse((parsed.scheme, parsed.netloc, path, "", new_query, ""))
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    @staticmethod
    def _norm_title(t: str) -> str:
        """タイトル文字列を単語重複スコアリング用に正規化する。

        モジュールレベルの _TITLE_BRACKET_RE・_TITLE_STATUS_RE を使用して
        [In preview] などの角括弧部分と Azure ステータス語を除去した上で
        記号を空白に変換して小文字化した文字列を返す。
        replace_unsourced_reference_links と verify_link_source_match の両方で
        共通して使用するため、ここに集約して重複定義を防ぐ。
        """
        t = _TITLE_BRACKET_RE.sub('', t)
        t = _TITLE_STATUS_RE.sub('', t)
        return re.sub(r'[^\w\s]', ' ', t.strip().lower())

    @staticmethod
    def collect_source_urls(*data_lists) -> frozenset[str]:
        """複数のデータリストから URL を収集して frozenset を返す。

        フィードから取得した記事・イベント URL を集約し、LLM 生成後の
        リンク検証（log_unsourced_reference_links）に使用する。
        list[dict] 形式では "url"・"event_url" キーを参照する。
        収集時に URL を正規化（utm_* などのトラッキングパラメータとフラグメントを除去）するため、
        ?utm_source=... などのトラッキングパラメータ付き URL とも一致する。
        id= などのコンテンツ識別パラメータは保持されるため、?id= で区別される
        異なる記事 URL（例: Azure アップデート）は別々のエントリとして管理される。
        """
        urls: set[str] = set()
        for data in data_lists:
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url") or item.get("event_url", "")
                    if url:
                        urls.add(SourceUrlTracker._normalize_url(url))
        return frozenset(urls)

    @staticmethod
    def log_unsourced_reference_links(article: str, source_urls: frozenset[str]) -> None:
        """リンクの URL がソースデータに含まれないものを検出・ログ出力する。

        LLM が提供されたソースデータ外の URL を生成した可能性がある箇所を可視化し、
        デバッグや品質改善に役立てる。URL の修正は validate_links() に委ねる。
        リンクの URL は正規化（utm_* などのトラッキングパラメータとフラグメントを除去）
        してから照合する。
        """
        ref_link_pattern = re.compile(
            r'\*\*リンク\*\*:\s*\[' + _LINK_LABEL_RE + r'\]\((https?://[^)]+)\)'
        )
        unsourced = [
            m.group(1) for m in ref_link_pattern.finditer(article)
            if SourceUrlTracker._normalize_url(m.group(1)) not in source_urls
        ]
        if unsourced:
            print(f"  ソース外リンク: {len(unsourced)} 件（HTTP 検証はこの後 validate_links() で実施）")
            for url in unsourced[:5]:
                print(f"    ℹ {url[:80]}")
        else:
            print("  リンク確認: 全てのリンクがソースデータと一致しています")

    @staticmethod
    def replace_unsourced_reference_links(
        article: str,
        source_data: "list[dict]",
        source_urls: frozenset[str],
    ) -> str:
        """ソース外のリンク URL をソースデータの URL に置換する。

        LLM がソースデータ外の URL を生成した場合、直近の ### 見出しと
        ソースデータのタイトルの単語一致でスコアリングし、最も近いソース URL に置換する。
        一致スコアが 0.5 未満でも、リンクラベルがソース名と一致する場合は
        そのソースの記事に絞って再スコアリングし（閾値 0.3）、置換を試みる。
        タイトル正規化は SourceUrlTracker._norm_title() を使用する。
        """
        title_url_pairs: list[tuple[str, str]] = []
        # ソース名 → (正規化タイトル, URL) リストのマッピング（ソース名ベースのフォールバック用）
        source_name_map: dict[str, list[tuple[str, str]]] = {}
        for item in source_data:
            if not (item.get("title") and item.get("url")):
                continue
            norm_t = SourceUrlTracker._norm_title(item["title"])
            url = item["url"]
            title_url_pairs.append((norm_t, url))
            source_name = item.get("source", "")
            if source_name:
                norm_source = re.sub(r'[^\w\s]', ' ', source_name.strip().lower())
                if norm_source not in source_name_map:
                    source_name_map[norm_source] = []
                source_name_map[norm_source].append((norm_t, url))

        if not title_url_pairs:
            return article

        def _best_match(hw: set, pairs: "list[tuple[str, str]]") -> "tuple[str, float]":
            # hw または title_words が空の場合はスキップ（見出しが空、またはタイトルが空語）
            best_url = ''
            best_score = 0.0
            for norm_t, src_url in pairs:
                title_words = set(norm_t.split())
                if not hw or not title_words:
                    continue
                common = hw & title_words
                score = len(common) / max(len(hw), len(title_words), 1)
                if score > best_score:
                    best_score = score
                    best_url = src_url
            return best_url, best_score

        # リンクラベルを独立したグループとして捕捉する（ソース名との照合に使用）
        ref_pattern = re.compile(
            r'(\*\*リンク\*\*:\s*)\[(' + _LINK_LABEL_RE + r')\]\((https?://[^)]+)\)'
        )

        lines = article.split('\n')
        current_heading = ''
        replaced = 0
        result: list[str] = []

        for line in lines:
            m_h = re.match(r'^###\s+(.+)', line)
            if m_h:
                current_heading = m_h.group(1).strip()

            if '**リンク**' in line and current_heading:
                norm_heading = SourceUrlTracker._norm_title(current_heading)
                heading_words = set(norm_heading.split())

                def _replacer(
                    m: re.Match,
                    # デフォルト引数で heading_words を定義時の値に束縛する（早期束縛）
                    _hw: set = heading_words,
                ) -> str:
                    nonlocal replaced
                    prefix = m.group(1)       # "**リンク**: "
                    link_label = m.group(2)   # リンクのラベルテキスト
                    url = m.group(3)          # URL
                    if SourceUrlTracker._normalize_url(url) in source_urls:
                        return m.group(0)

                    # 1次マッチング: 見出し語 vs 全ソースタイトル語（閾値 0.5）
                    best_url, best_score = _best_match(_hw, title_url_pairs)
                    if best_url and best_score >= 0.5:
                        replaced += 1
                        print(
                            f"    ✓ ソース外 URL 置換: {url[:50]} → {best_url[:50]}"
                            f" (score={best_score:.2f})"
                        )
                        return f"{prefix}[{link_label}]({best_url})"

                    # 2次マッチング: リンクラベルがソース名と一致する場合、
                    # そのソースの記事に絞って再マッチング（閾値 0.3）
                    # LLM がソース名をラベルに使い、ソース名から URL を推測するケースを修正する。
                    # 単語トークン単位で照合し、部分文字列の誤マッチを防ぐ。
                    norm_label = re.sub(r'[^\w\s]', ' ', link_label.strip().lower())
                    norm_label_words = set(norm_label.split())
                    for norm_source, pairs in source_name_map.items():
                        source_words = set(norm_source.split())
                        # ソース名の全単語がラベルに含まれるか、またはその逆（双方向部分集合）
                        if len(norm_source) >= 4 and source_words and (
                            source_words <= norm_label_words
                            or norm_label_words <= source_words
                        ):
                            fallback_url, fallback_score = _best_match(_hw, pairs)
                            if fallback_url and fallback_score >= 0.3:
                                replaced += 1
                                print(
                                    f"    ✓ ソース名ベース URL 置換: {url[:50]} → {fallback_url[:50]}"
                                    f" (source='{norm_source}', score={fallback_score:.2f})"
                                )
                                return f"{prefix}[{link_label}]({fallback_url})"

                    return m.group(0)

                line = ref_pattern.sub(_replacer, line)

            result.append(line)

        if replaced:
            print(f"  ソース外リンク修正: {replaced} 件をソースデータの URL に置換しました")
        return '\n'.join(result)

    @staticmethod
    def verify_link_source_match(
        article: str,
        source_data: "list[dict]",
    ) -> str:
        """リンク URL とソースデータの内容近似性を検証し、不一致を修正して返す。

        各トピックの **リンク** URL をソースデータの title・description と照合し、
        トピック見出しとの単語重複スコアが低い場合（閾値 0.15 未満）に警告をログ出力する。
        さらに全ソースデータから最適な URL（スコア >= 0.3）が見つかれば記事を修正して返す。
        Azure・Google News・テックブログ等の全セクションに対して共通して適用する。

        以下の 4 段階のチェックを順に実施する：

        **① ドメイン不一致チェック**（最強シグナル）
        source_data 内の URL ドメイン集合を構築し、記事リンクのドメインがその集合に含まれ
        ない場合は「ドメイン不一致」と判定する。日本国内ベンダーサイトや非公式サイトへの
        誤リンクをこのチェックで検出できる。修正候補が見つかれば URL を置換し、
        [ドメイン不一致→修正済み] をログに記録する。

        **② ラベルとリンク先の類似スコアチェック**（補助検証）
        LLM はラベルにソースタイトルを直接コピーすることが多い性質を活用する。
        ラベル語とリンク先の title・description それぞれに対してスコアを算出し、
        高い方を採用する（タイトルに含まれないキーワードが説明文にある場合も正しく評価）。
        ラベルスコアが閾値 0.3 未満で修正候補がある場合は [ラベル不一致→修正済み] で修正、
        候補がない場合は [ラベル不一致] として警告のみ出力する。

        **③ 見出しとリンク先の類似スコアチェック**（既存検証）
        日本語見出し語と英語ソース（title + description）の単語重複スコアが 0.15 未満の
        場合に警告を出力し、修正候補があれば URL を置換する。

        **④ HTTP ページタイトルチェック**（最終確認・全セクション対応）
        実際のリンク先ページを HTTP で取得しページタイトルとラベル・見出しを比較する。
        静的チェックではフィード取得時のスナップショットのみ参照していたが、
        このチェックでは実際のリンク先コンテンツを確認するためより信頼性が高い。
        ラベル/見出しとページタイトルのスコアが 0.3 未満の場合に
        [ページタイトル不一致→修正済み] で修正、または [ページタイトル不一致] で警告する。
        同一 URL の結果はキャッシュして重複 HTTP リクエストを避ける。
        ネットワーク障害時はソフトフェイル（空タイトル → チェックスキップ）。

        スコアは len(共通語) / max(len(A語), len(B語)) で算出する
        （簡易重複率。標準 Jaccard 指数とは異なる）。
        タイトル正規化は SourceUrlTracker._norm_title() を使用する。
        """
        _LINK_MATCH_THRESHOLD = 0.15
        _REPAIR_THRESHOLD = 0.3
        # リンクラベルとリンク先ソースタイトルの類似スコア閾値。
        # LLM はラベルにソースタイトルを直接コピーすることが多いため、
        # この閾値未満の場合は URL の誤りを疑って修正を試みる。
        _LABEL_TITLE_THRESHOLD = 0.3

        # URL → source_item マッピングを構築（正規化済み URL をキーとする）
        url_to_item: dict[str, dict] = {}
        # 全ソースタイトル → URL ペアリスト（修正用のベストマッチ検索に使用）
        title_url_pairs: list[tuple[str, str]] = []
        # source_data URL のドメイン集合（想定外ドメインのリンクを検出するため）
        source_domains: set[str] = set()
        for item in source_data:
            url = item.get("url", "")
            if url:
                norm = SourceUrlTracker._normalize_url(url)
                url_to_item[norm] = item
                try:
                    source_domains.add(_normalize_domain(urlparse(url)))
                except ValueError as e:
                    print(
                        f"  ⚠ source_data URL のパース失敗（このURLのドメイン収集をスキップして続行）:"
                        f" {url!r} ({e})"
                    )
            if item.get("title") and item.get("url"):
                title_url_pairs.append(
                    (SourceUrlTracker._norm_title(item["title"]), item["url"])
                )

        if not url_to_item:
            return article

        def _best_match(hw: set, pairs: "list[tuple[str, str]]") -> "tuple[str, float]":
            best_url = ''
            best_score = 0.0
            for norm_t, src_url in pairs:
                title_words = set(norm_t.split())
                if not hw or not title_words:
                    continue
                common = hw & title_words
                score = len(common) / max(len(hw), len(title_words), 1)
                if score > best_score:
                    best_score = score
                    best_url = src_url
            return best_url, best_score

        # リンクラベルを独立したグループとして捕捉する（修正時にラベルを保持するため）
        ref_pattern = re.compile(
            r'(\*\*リンク\*\*:\s*)\[(' + _LINK_LABEL_RE + r')\]\((https?://[^)]+)\)'
        )

        lines = article.split('\n')
        current_heading = ''
        low_similarity: list[str] = []
        repaired = 0
        result: list[str] = []
        # URL → ページタイトルのキャッシュ（同じ URL を複数トピックで参照する場合の重複 HTTP を避ける）
        _page_title_cache: dict[str, str] = {}

        for line in lines:
            m_h = re.match(r'^###\s+(.+)', line)
            if m_h:
                current_heading = m_h.group(1).strip()
                result.append(line)
                continue

            if '**リンク**' in line and current_heading:
                heading_words = set(SourceUrlTracker._norm_title(current_heading).split())

                def _checker(
                    m: re.Match,
                    _hw: set = heading_words,
                    _heading: str = current_heading,
                ) -> str:
                    nonlocal repaired
                    prefix = m.group(1)
                    label = m.group(2)
                    url = m.group(3)

                    # ラベル語はドメインチェックや item is None の前に算出する。
                    # ドメイン不一致時の修正でラベル語を使用するためここで早期に計算する。
                    norm_label_words = set(SourceUrlTracker._norm_title(label).split())

                    norm_url = SourceUrlTracker._normalize_url(url)
                    item = url_to_item.get(norm_url)

                    # ① ドメイン不一致チェック（source_data に存在しないドメインの URL）。
                    # 日本国内ベンダーサイトや非公式サイトへのリンクを検出するための
                    # 最強のシグナル。URL が source_data に含まれていない（item is None）か、
                    # または含まれていてもドメインが source_data 全体と一致しない場合に検出する。
                    try:
                        link_domain = _normalize_domain(urlparse(url))
                    except ValueError as e:
                        print(
                            f"  ⚠ 記事リンク URL のパース失敗（ドメインチェックをスキップ）:"
                            f" {url!r} ({e})"
                        )
                        link_domain = ""
                    # link_domain が空（パース失敗）の場合はドメインチェックをスキップして誤検知を防ぐ
                    if source_domains and link_domain and link_domain not in source_domains:
                        # ラベル語を優先し、空の場合は日本語混じりの見出し語をフォールバックに使う。
                        # 見出し語フォールバックにより、ラベルが空でも英語産業語（製品名等）が
                        # 重なればベストマッチが機能する。
                        repair_words = norm_label_words if norm_label_words else _hw
                        best_domain_url, best_domain_score = _best_match(
                            repair_words, title_url_pairs
                        )
                        if (
                            best_domain_score >= _REPAIR_THRESHOLD
                            and best_domain_url
                            and best_domain_url != url
                        ):
                            repaired += 1
                            low_similarity.append(
                                f"[ドメイン不一致→修正済み][{_heading[:50]}]"
                                f" {url[:50]} → {best_domain_url[:50]}"
                                f" (domain={link_domain},"
                                f" repair_score={best_domain_score:.2f})"
                            )
                            return f"{prefix}[{label}]({best_domain_url})"
                        low_similarity.append(
                            f"[ドメイン不一致][{_heading[:50]}]"
                            f" {url[:60]}"
                            f" (domain={link_domain})"
                        )
                        if item is None:
                            return m.group(0)

                    if item is None:
                        return m.group(0)

                    source_text = item.get("title", "") + " " + item.get("description", "")
                    source_words = set(SourceUrlTracker._norm_title(source_text).split())

                    if not _hw or not source_words:
                        return m.group(0)

                    common = _hw & source_words
                    score = len(common) / max(len(_hw), len(source_words), 1)

                    # ② ラベルとリンク先ソースの類似スコアチェック（補助検証）。
                    # LLM はラベルにソースタイトルを直接コピーすることが多いため、
                    # ラベルとリンク先タイトル・説明文の一致が低い場合は URL の誤りを疑う。
                    # タイトルと説明文の双方に対してスコアを算出し、高い方を採用することで
                    # タイトルに現れないキーワードが説明文に含まれる場合も正しく評価する。
                    source_title_words = set(
                        SourceUrlTracker._norm_title(item.get("title", "")).split()
                    )
                    source_desc_words = set(
                        SourceUrlTracker._norm_title(item.get("description", "")).split()
                    )
                    label_score_vs_title = (
                        len(norm_label_words & source_title_words)
                        / max(len(norm_label_words), len(source_title_words), 1)
                        if norm_label_words and source_title_words
                        else 0.0
                    )
                    label_score_vs_desc = (
                        len(norm_label_words & source_desc_words)
                        / max(len(norm_label_words), len(source_desc_words), 1)
                        if norm_label_words and source_desc_words
                        else 0.0
                    )
                    # タイトルまたは説明文のいずれかで一致すれば正しいリンクと見なす
                    label_title_score = max(label_score_vs_title, label_score_vs_desc)

                    if norm_label_words and (source_title_words or source_desc_words):
                        if label_title_score < _LABEL_TITLE_THRESHOLD:
                            # ラベル語で全ソースから最適 URL を検索して修正を試みる。
                            # この _best_match 呼び出しはラベル語（英語タイトル由来）を使用するため、
                            # 後述の見出し語（日本語混じり）を使う _best_match とは意図的に別物。
                            best_by_label_url, best_by_label_score = _best_match(
                                norm_label_words, title_url_pairs
                            )
                            if (
                                best_by_label_score >= _REPAIR_THRESHOLD
                                and best_by_label_url
                                and best_by_label_url != url
                            ):
                                repaired += 1
                                low_similarity.append(
                                    f"[ラベル不一致→修正済み][{_heading[:50]}]"
                                    f" {url[:50]} → {best_by_label_url[:50]}"
                                    f" (label_score={label_title_score:.2f},"
                                    f" repair_score={best_by_label_score:.2f})"
                                )
                                return f"{prefix}[{label}]({best_by_label_url})"
                            # 修正候補なし: 警告のみ
                            low_similarity.append(
                                f"[ラベル不一致][{_heading[:50]}]"
                                f" {url[:60]}"
                                f" (label_score={label_title_score:.2f},"
                                f" label='{label[:40]}')"
                            )

                    if score < _LINK_MATCH_THRESHOLD:
                        # ソース全体から最適 URL を検索して修正を試みる
                        best_url, best_score = _best_match(_hw, title_url_pairs)
                        if best_url and best_score >= _REPAIR_THRESHOLD and best_url != url:
                            repaired += 1
                            low_similarity.append(
                                f"[修正済み][{_heading[:50]}]"
                                f" {url[:50]} → {best_url[:50]}"
                                f" (before={score:.2f}, after={best_score:.2f})"
                            )
                            return f"{prefix}[{label}]({best_url})"
                        # 修正候補なし: 警告のみ
                        low_similarity.append(
                            f"[{_heading[:50]}]"
                            f" → {url[:60]}"
                            f" (score={score:.2f},"
                            f" source='{item.get('title', '')[:40]}')"
                        )

                    # ④ HTTP ページタイトルチェック（最も時間のかかる最終確認）。
                    # 静的チェック（①〜③）ではソース_data のスナップショットのみ参照していたが、
                    # ここでは実際のリンク先ページを HTTP で取得してページタイトルとラベルを比較する。
                    # Azure に限らず全セクション・全ドメインに対して共通して適用されるため、
                    # 日本ベンダーサイト等への誤リンクも「ページタイトルが全然違う」として検出可能。
                    # ネットワーク障害時はソフトフェイル（空タイトル → チェックスキップ）。
                    # キャッシュキーは正規化済み URL（utm_* 等の異なりを同一視）。
                    # DAILY_NEWS_FETCH_PAGE_TITLE=0 で無効化できる。
                    if _FETCH_PAGE_TITLE_ENABLED:
                        _PAGE_TITLE_THRESHOLD = 0.3
                        if norm_url not in _page_title_cache:
                            _page_title_cache[norm_url] = _fetch_page_title(url)
                        page_title = _page_title_cache[norm_url]
                        if page_title:
                            page_title_words = set(
                                SourceUrlTracker._norm_title(page_title).split()
                            )
                            # ラベル語と見出し語の両方でページタイトルとのスコアを算出し、高い方を採用。
                            # LLM がラベルをコピーしなかった場合でも見出し語で検出できるようにする。
                            label_vs_page_score = (
                                len(norm_label_words & page_title_words)
                                / max(len(norm_label_words), len(page_title_words), 1)
                                if norm_label_words and page_title_words
                                else 0.0
                            )
                            heading_vs_page_score = (
                                len(_hw & page_title_words)
                                / max(len(_hw), len(page_title_words), 1)
                                if _hw and page_title_words
                                else 0.0
                            )
                            page_score = max(label_vs_page_score, heading_vs_page_score)
                            if page_score < _PAGE_TITLE_THRESHOLD:
                                # ラベル語でベストマッチを探して修正を試みる
                                repair_words = norm_label_words if norm_label_words else _hw
                                best_page_url, best_page_score = _best_match(
                                    repair_words, title_url_pairs
                                )
                                if (
                                    best_page_score >= _REPAIR_THRESHOLD
                                    and best_page_url
                                    and best_page_url != url
                                ):
                                    repaired += 1
                                    low_similarity.append(
                                        f"[ページタイトル不一致→修正済み][{_heading[:50]}]"
                                        f" {url[:50]} → {best_page_url[:50]}"
                                        f" (page_title='{page_title[:40]}',"
                                        f" page_score={page_score:.2f})"
                                    )
                                    return f"{prefix}[{label}]({best_page_url})"
                                low_similarity.append(
                                    f"[ページタイトル不一致][{_heading[:50]}]"
                                    f" {url[:60]}"
                                    f" (page_title='{page_title[:40]}',"
                                    f" page_score={page_score:.2f})"
                                )

                    return m.group(0)

                line = ref_pattern.sub(_checker, line)

            result.append(line)

        if low_similarity:
            fixed = sum(1 for m in low_similarity if "修正済み" in m)
            unfixed = len(low_similarity) - fixed
            print(
                f"  ⚠ リンク内容近似性チェック: {len(low_similarity)} 件の低スコア"
                f"（修正={fixed} 件、警告のみ={unfixed} 件）"
            )
            for msg in low_similarity:
                print(f"    ℹ {msg}")
        else:
            print("  リンク内容近似性チェック: 問題なし")

        return '\n'.join(result)
