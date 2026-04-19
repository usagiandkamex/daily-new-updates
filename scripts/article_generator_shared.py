"""
デイリーアップデート・テクニカル雑談の共通生成ユーティリティ

generate_daily_update.py と generate_smallchat.py の両ワークフローで
共有するクラスおよび関数を提供する。共通機能をここで一元管理することで、
改善や修正を両ワークフローに同時に反映させることができる。
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse, urlunparse

import feedparser
import requests
from googlenewsdecoder import new_decoderv1

# 日本標準時
JST = timezone(timedelta(hours=9))

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
      2. 各トピックに **要約** と **参考リンク** が含まれること
      3. **参考リンク** が [タイトル](URL) 形式であること
      4. セクション末尾に不要な締め文がないこと
      5. 連続 --- セパレータや孤立セパレータがないこと
    修正可能な問題は自動修正し、全ての検出事項をログ出力する。
    コミュニティイベントセクション（「コミュニティ」を含む見出し）の
    箇条書きサブセクション（📅・📝 で始まる見出し）は要約・参考リンクのチェックを省略する。
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


class SourceUrlTracker:
    """フィード取得したソース URL を管理し、LLM 生成後の参考リンク検証に使用するクラス。

    デイリーアップデート・テクニカル雑談の両ワークフローで共通して使用する。
    LLM が提供されたソースデータ外の URL を生成した可能性がある箇所を可視化し、
    デバッグや品質改善に役立てる。
    """

    @staticmethod
    def _normalize_url(url: str) -> str:
        """URL を正規化してクエリパラメータとフラグメントを除去する。

        ?utm_source=... などのトラッキングパラメータや #section のフラグメントを
        除去し、スキーム・ホスト・パスのみを残す。これにより、同一記事を指す
        URL のバリエーションを同一視できる。
        """
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    @staticmethod
    def collect_source_urls(*data_lists) -> frozenset[str]:
        """複数のデータリストから URL を収集して frozenset を返す。

        フィードから取得した記事・イベント URL を集約し、LLM 生成後の
        参考リンク検証（log_unsourced_reference_links）に使用する。
        list[dict] 形式では "url"・"event_url" キーを参照する。
        収集時に URL を正規化（クエリパラメータ・フラグメント除去）するため、
        ?utm_source=... などのパラメータ付き URL とも一致する。
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
        """参考リンクの URL がソースデータに含まれないものを検出・ログ出力する。

        LLM が提供されたソースデータ外の URL を生成した可能性がある箇所を可視化し、
        デバッグや品質改善に役立てる。URL の修正は validate_links() に委ねる。
        参考リンクの URL は正規化（クエリパラメータ除去）してから照合する。
        """
        ref_link_pattern = re.compile(
            r'\*\*参考リンク\*\*:\s*\[' + _LINK_LABEL_RE + r'\]\((https?://[^)]+)\)'
        )
        unsourced = [
            m.group(1) for m in ref_link_pattern.finditer(article)
            if SourceUrlTracker._normalize_url(m.group(1)) not in source_urls
        ]
        if unsourced:
            print(f"  ソース外参考リンク: {len(unsourced)} 件（HTTP 検証はこの後 validate_links() で実施）")
            for url in unsourced[:5]:
                print(f"    ℹ {url[:80]}")
        else:
            print("  参考リンク確認: 全てのリンクがソースデータと一致しています")
