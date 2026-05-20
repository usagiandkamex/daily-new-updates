"""
generate_events_calendar.py の純粋ロジックの単体テスト

外部 HTTP 通信は unittest.mock でスタブし、実際のネットワーク接続は行わない。
"""

import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_events_calendar import (
    _build_search_months,
    _is_it_event,
    _parse_started_at_api,
    _ConnpassEventPageParser,
    _HTMLTextExtractor,
    _extract_text_from_html,
    _is_connpass_event_url,
    _fetch_api_events,
    _truncate_description,
    fetch_events,
    fetch_vendor_news_events,
    VENDOR_EVENT_NEWS_FEEDS,
    VENDOR_EVENT_LOOKBACK_DAYS,
    VENDOR_REPORT_LOOKBACK_DAYS,
    main,
    MAX_DESCRIPTION_CHARS,
    JST,
)


# ---------------------------------------------------------------------------
# _build_search_months
# ---------------------------------------------------------------------------

class TestBuildSearchMonths(unittest.TestCase):
    """_build_search_months() のテスト"""

    def test_single_month(self):
        """lookahead=0 の場合は当月のみ返す。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        result = _build_search_months(today, 0)
        self.assertEqual(result, ["202605"])

    def test_two_months_ahead(self):
        """lookahead=2 の場合は当月 + 2か月先まで 3 件返す。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        result = _build_search_months(today, 2)
        self.assertEqual(result, ["202605", "202606", "202607"])

    def test_year_rollover(self):
        """12月から lookahead=2 の場合に年をまたいで正しくリストを返す。"""
        today = datetime(2025, 12, 1, tzinfo=JST)
        result = _build_search_months(today, 2)
        self.assertEqual(result, ["202512", "202601", "202602"])

    def test_january_start(self):
        """1月始まりで lookahead=1 が正しく 2 件を返す。"""
        today = datetime(2026, 1, 10, tzinfo=JST)
        result = _build_search_months(today, 1)
        self.assertEqual(result, ["202601", "202602"])

    def test_returns_list(self):
        """戻り値が list であること。"""
        today = datetime(2026, 3, 1, tzinfo=JST)
        result = _build_search_months(today, 1)
        self.assertIsInstance(result, list)

    def test_length(self):
        """結果の件数は lookahead + 1 であること。"""
        for n in range(4):
            today = datetime(2026, 4, 1, tzinfo=JST)
            result = _build_search_months(today, n)
            self.assertEqual(len(result), n + 1)


# ---------------------------------------------------------------------------
# _parse_started_at_api
# ---------------------------------------------------------------------------

class TestParseStartedAtApi(unittest.TestCase):
    """_parse_started_at_api() のテスト"""

    def test_converts_zulu_to_jst(self):
        """UTC(Z)表記を JST へ変換する。"""
        self.assertEqual(
            _parse_started_at_api("2026-05-20T01:00:00Z"),
            "2026/05/20 10:00",
        )

    def test_invalid_format_returns_empty(self):
        """不正な日時文字列は空文字列を返す。"""
        self.assertEqual(_parse_started_at_api("not-a-date"), "")


# ---------------------------------------------------------------------------
# _is_it_event
# ---------------------------------------------------------------------------

class TestIsItEvent(unittest.TestCase):
    """_is_it_event() のテスト"""

    def test_python_in_title(self):
        """タイトルに 'python' を含むと True。"""
        self.assertTrue(_is_it_event("Python 勉強会", ""))

    def test_aws_in_desc(self):
        """説明に 'AWS' を含むと True（大文字小文字不問）。"""
        self.assertTrue(_is_it_event("テスト", "AWS hands-on"))

    def test_kubernetes_abbreviation(self):
        """'k8s' を含むと True。"""
        self.assertTrue(_is_it_event("k8s ハンズオン", ""))

    def test_word_boundary_ai(self):
        """'ai' が単語境界で一致すると True。"""
        self.assertTrue(_is_it_event("AI セミナー", ""))

    def test_word_boundary_ai_in_word(self):
        """'ai' が単語内（例: 'train'）に埋め込まれている場合は False。"""
        self.assertFalse(_is_it_event("train the trainer", "painting workshop"))

    def test_word_boundary_go(self):
        """'go' が単語境界で一致すると True。"""
        self.assertTrue(_is_it_event("Go言語入門", ""))

    def test_word_boundary_go_inside_word(self):
        """'go' が別の単語に埋め込まれている場合（例: 'golang'）はマッチしないこと。"""
        self.assertFalse(_is_it_event("golang study", "web design"))

    def test_non_it_event(self):
        """IT 関連キーワードを含まない場合は False。"""
        self.assertFalse(_is_it_event("料理教室", "楽しいクッキング体験"))

    def test_case_insensitive(self):
        """キーワード判定は大文字小文字を区別しない。"""
        self.assertTrue(_is_it_event("AZURE STUDY", ""))
        self.assertTrue(_is_it_event("Kubernetes hands-on", ""))

    def test_it_keywords_in_combined_text(self):
        """タイトルと説明を結合して判定すること。"""
        self.assertTrue(_is_it_event("春の勉強会", "Dockerの基礎を学びます"))

    def test_sre_word_boundary(self):
        """'sre' が単語境界で一致すると True。"""
        self.assertTrue(_is_it_event("SRE勉強会", ""))

    def test_jaws_ug(self):
        """'jaws' を含むと True。"""
        self.assertTrue(_is_it_event("JAWSUG 東京", "AWS コミュニティ"))

    def test_engineer_keyword(self):
        """'エンジニア' を含むと True。"""
        self.assertTrue(_is_it_event("エンジニア向けイベント", ""))


# ---------------------------------------------------------------------------
# _ConnpassEventPageParser
# ---------------------------------------------------------------------------

class TestConnpassEventPageParser(unittest.TestCase):
    """_ConnpassEventPageParser のテスト"""

    def _parse(self, html: str) -> str:
        parser = _ConnpassEventPageParser()
        parser.feed(html)
        return parser.get_text()

    def test_extracts_text_from_target_div(self):
        """event_description_content クラスの div からテキストを取得する。"""
        html = (
            '<div class="event_description_content">'
            '<p>イベント説明本文です。</p>'
            '</div>'
        )
        result = self._parse(html)
        self.assertIn("イベント説明本文です。", result)

    def test_ignores_text_outside_target(self):
        """対象クラス外のテキストは含まない。"""
        html = (
            '<div class="other_class">無関係テキスト</div>'
            '<div class="event_description_content"><p>対象テキスト</p></div>'
        )
        result = self._parse(html)
        self.assertIn("対象テキスト", result)
        self.assertNotIn("無関係テキスト", result)

    def test_empty_when_no_target_div(self):
        """対象クラスの div がない場合は空文字列。"""
        html = '<div class="other"><p>テキスト</p></div>'
        result = self._parse(html)
        self.assertEqual(result, "")

    def test_nested_tags(self):
        """ネストされたタグ内のテキストも取得できる。"""
        html = (
            '<div class="event_description_content">'
            '<h2>見出し</h2><p>段落テキスト</p><ul><li>リスト項目</li></ul>'
            '</div>'
        )
        result = self._parse(html)
        self.assertIn("見出し", result)
        self.assertIn("段落テキスト", result)
        self.assertIn("リスト項目", result)

    def test_multiple_classes_on_target(self):
        """複数クラスが付いていても event_description_content があれば対象。"""
        html = (
            '<div class="section event_description_content main">'
            '<p>説明文</p>'
            '</div>'
        )
        result = self._parse(html)
        self.assertIn("説明文", result)

    def test_html_entities_decoded(self):
        """convert_charrefs=True により HTML エンティティが自動デコードされる。"""
        html = (
            '<div class="event_description_content">'
            '&lt;サンプル&gt; &amp; テスト'
            '</div>'
        )
        result = self._parse(html)
        self.assertIn("<サンプル>", result)
        self.assertIn("& テスト", result)

    def test_get_text_strips_blank_parts(self):
        """空白のみのパーツは結果に含めない。"""
        html = (
            '<div class="event_description_content">'
            '  \n  <p>実テキスト</p>  \t  '
            '</div>'
        )
        result = self._parse(html)
        self.assertNotEqual(result, "")
        self.assertIn("実テキスト", result)


# ---------------------------------------------------------------------------
# _HTMLTextExtractor / _extract_text_from_html
# ---------------------------------------------------------------------------

class TestHTMLTextExtractor(unittest.TestCase):
    """_HTMLTextExtractor と _extract_text_from_html() のテスト"""

    def test_strips_html_tags(self):
        """HTML タグが除去されてテキストのみ返る。"""
        result = _extract_text_from_html("<p>Hello <strong>world</strong></p>")
        self.assertIn("Hello", result)
        self.assertIn("world", result)
        self.assertNotIn("<p>", result)
        self.assertNotIn("<strong>", result)

    def test_strips_japanese_html(self):
        """日本語 HTML タグが除去されてテキストのみ返る。"""
        html = "<div><h2>タイトル</h2><p>イベントの説明文です。</p></div>"
        result = _extract_text_from_html(html)
        self.assertIn("タイトル", result)
        self.assertIn("イベントの説明文です。", result)
        self.assertNotIn("<h2>", result)

    def test_empty_string_returns_empty(self):
        """空文字列は空文字列を返す。"""
        self.assertEqual(_extract_text_from_html(""), "")

    def test_plain_text_returns_unchanged(self):
        """HTML タグを含まない文字列はそのまま返る。"""
        self.assertEqual(_extract_text_from_html("プレーンテキスト"), "プレーンテキスト")

    def test_html_entities_decoded(self):
        """HTML エンティティがデコードされる。"""
        result = _extract_text_from_html("&lt;sample&gt; &amp; test")
        self.assertIn("<sample>", result)
        self.assertIn("& test", result)

    def test_normalizes_whitespace(self):
        """余分な空白が正規化される。"""
        result = _extract_text_from_html("<p>  text1  </p><p>  text2  </p>")
        self.assertNotIn("  ", result)
        self.assertIn("text1", result)
        self.assertIn("text2", result)

    def test_only_tags_returns_empty(self):
        """テキストコンテンツがない HTML タグのみの文字列は空文字列を返す。"""
        self.assertEqual(_extract_text_from_html("<br/><hr/>"), "")


# ---------------------------------------------------------------------------
# 説明文の切り詰めロジック
# ---------------------------------------------------------------------------

class TestDescriptionTruncation(unittest.TestCase):
    """_truncate_description() のテスト"""

    def test_short_text_unchanged(self):
        """MAX_DESCRIPTION_CHARS 以下のテキストは変更されない。"""
        text = "短いテキスト"
        self.assertEqual(_truncate_description(text), text)

    def test_exact_length_unchanged(self):
        """ちょうど MAX_DESCRIPTION_CHARS 文字のテキストは変更されない。"""
        text = "あ" * MAX_DESCRIPTION_CHARS
        self.assertEqual(_truncate_description(text), text)

    def test_long_text_truncated_with_ellipsis(self):
        """MAX_DESCRIPTION_CHARS を超えるテキストは '…' で終わり、合計長は MAX 以内。"""
        text = "あ " * (MAX_DESCRIPTION_CHARS // 2 + 50)
        result = _truncate_description(text)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), MAX_DESCRIPTION_CHARS)

    def test_truncation_at_word_boundary(self):
        """単語境界（スペース）で切り詰めること。"""
        prefix = "hello " * (MAX_DESCRIPTION_CHARS // 6 + 1)
        result = _truncate_description(prefix)
        self.assertTrue(result.endswith("…"))
        # '…' の直前が単語内テキスト（スペースなし）であること
        self.assertFalse(result[:-1].endswith(" "))
        self.assertLessEqual(len(result), MAX_DESCRIPTION_CHARS)

    def test_custom_max_chars(self):
        """max_chars 引数で切り詰め長を変更できる。'…' 含めて max_chars 以内。"""
        result = _truncate_description("hello world foo bar baz", max_chars=10)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), 10)

    def test_no_space_truncation(self):
        """スペースを含まないテキストでも max_chars 以内に収まること。"""
        text = "あ" * 1000
        result = _truncate_description(text, max_chars=50)
        self.assertTrue(result.endswith("…"))
        self.assertEqual(len(result), 50)


# ---------------------------------------------------------------------------
# _is_connpass_event_url
# ---------------------------------------------------------------------------

class TestIsConnpassEventUrl(unittest.TestCase):
    """_is_connpass_event_url() のテスト（SSRF 対策）"""

    def test_https_connpass_root(self):
        self.assertTrue(_is_connpass_event_url("https://connpass.com/event/123/"))

    def test_https_connpass_subdomain(self):
        self.assertTrue(_is_connpass_event_url("https://hoge.connpass.com/event/123/"))

    def test_http_rejected(self):
        """http:// は許可しない（HTTPS のみ）。"""
        self.assertFalse(_is_connpass_event_url("http://connpass.com/event/123/"))

    def test_other_host_rejected(self):
        self.assertFalse(_is_connpass_event_url("https://evil.example.com/event/"))

    def test_lookalike_host_rejected(self):
        """connpass を含むだけのドメインは許可しない（サブドメイン境界チェック）。"""
        self.assertFalse(_is_connpass_event_url("https://evilconnpass.com/event/"))

    def test_non_event_path_rejected(self):
        """connpass.com でも /event/ 配下でない URL は許可しない。"""
        self.assertFalse(_is_connpass_event_url("https://connpass.com/"))
        self.assertFalse(_is_connpass_event_url("https://connpass.com/search/"))
        self.assertFalse(_is_connpass_event_url("https://connpass.com/user/foo/"))

    def test_empty_rejected(self):
        self.assertFalse(_is_connpass_event_url(""))

    def test_invalid_url_rejected(self):
        """壊れた URL でも例外を投げず False を返す。"""
        self.assertFalse(_is_connpass_event_url("not a url"))


# ---------------------------------------------------------------------------
# fetch_events (HTTP モック)
# ---------------------------------------------------------------------------

def _make_response(content: bytes = b"<rss/>") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def _make_api_response(
    events: list[dict],
    *,
    results_returned: int | None = None,
    results_available: int | None = None,
) -> MagicMock:
    resp = _make_response()
    payload: dict = {"events": events}
    if results_returned is not None:
        payload["results_returned"] = results_returned
    if results_available is not None:
        payload["results_available"] = results_available
    resp.json = MagicMock(return_value=payload)
    return resp


def _make_feed(*entries: dict) -> MagicMock:
    """feedparser.parse の戻り値をスタブする。entries は dict のリスト。"""
    feed = MagicMock()
    feed.entries = [
        # entry.get(key, default) を使うため dict そのままを渡す
        e for e in entries
    ]
    return feed


class TestFetchEvents(unittest.TestCase):
    """fetch_events() の統合テスト（requests / feedparser はモック）"""

    def setUp(self):
        # テスト中の RSS 取得回数を抑えるため lookahead を 0 か月にする
        patcher = patch("generate_events_calendar.CALENDAR_LOOKAHEAD_MONTHS", 0)
        self.addCleanup(patcher.stop)
        patcher.start()
        # デフォルトは RSS 経路を使う（API キー経路は個別テストで上書き）
        self._orig_connpass_api_key = os.environ.pop("CONNPASS_API_KEY", None)
        self.addCleanup(self._restore_connpass_api_key)
        # 説明文取得（HTTP）はスキップ
        enrich_patcher = patch(
            "generate_events_calendar._enrich_descriptions", lambda events: None
        )
        self.addCleanup(enrich_patcher.stop)
        enrich_patcher.start()
        # ベンダーイベント取得はスキップ（TestFetchVendorNewsEvents で個別テスト）
        vendor_patcher = patch(
            "generate_events_calendar.fetch_vendor_news_events", return_value=[]
        )
        self.addCleanup(vendor_patcher.stop)
        vendor_patcher.start()

    def _restore_connpass_api_key(self):
        if self._orig_connpass_api_key is None:
            os.environ.pop("CONNPASS_API_KEY", None)
        else:
            os.environ["CONNPASS_API_KEY"] = self._orig_connpass_api_key

    def _entry(self, title: str, link: str, summary: str = "AWS hands-on",
               published_dt: datetime | None = None) -> dict:
        e: dict = {"title": title, "link": link, "summary": summary}
        if published_dt is not None:
            utc = published_dt.astimezone(timezone.utc)
            e["published_parsed"] = (
                utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second, 0, 0, 0
            )
        return e

    def test_collects_pref_and_online_with_dedup(self):
        """都道府県とオンラインの両系統からイベントを収集し、URL重複を排除する。"""
        today = datetime(2026, 5, 15, 9, 0, tzinfo=JST)
        future = datetime(2026, 5, 20, 19, 0, tzinfo=JST)
        # 2 都県 + online で 3 回呼ばれる。1 件目を東京、2 件目を神奈川、
        # 3 件目（オンライン）に同一 URL を含めて重複排除を検証
        feeds_iter = iter([
            _make_feed(
                self._entry("AWS 勉強会", "https://connpass.com/event/1/", published_dt=future),
            ),
            _make_feed(
                self._entry("Kubernetes ハンズオン", "https://connpass.com/event/2/", published_dt=future),
            ),
            _make_feed(
                # 重複（東京で取得済み）→ スキップされる
                self._entry("AWS 勉強会", "https://connpass.com/event/1/", published_dt=future),
                self._entry("Python オンライン", "https://connpass.com/event/3/", published_dt=future),
            ),
        ])

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        urls = [e["event_url"] for e in events]
        self.assertEqual(len(events), 3)
        self.assertEqual(set(urls), {
            "https://connpass.com/event/1/",
            "https://connpass.com/event/2/",
            "https://connpass.com/event/3/",
        })
        # place が正しく付与されている
        place_by_url = {e["event_url"]: e["place"] for e in events}
        self.assertEqual(place_by_url["https://connpass.com/event/1/"], "東京都")
        self.assertEqual(place_by_url["https://connpass.com/event/2/"], "神奈川県")
        self.assertEqual(place_by_url["https://connpass.com/event/3/"], "オンライン")

    def test_filters_non_it_events(self):
        """IT キーワードを含まないイベントは除外される。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        future = datetime(2026, 5, 20, tzinfo=JST)
        feeds_iter = iter([
            _make_feed(
                self._entry("料理教室", "https://connpass.com/event/100/",
                            summary="楽しいクッキング", published_dt=future),
                self._entry("Python 入門", "https://connpass.com/event/101/",
                            summary="Python の基礎", published_dt=future),
            ),
            _make_feed(),
            _make_feed(),
        ])

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        urls = [e["event_url"] for e in events]
        self.assertEqual(urls, ["https://connpass.com/event/101/"])

    def test_filters_past_events_by_date(self):
        """開催日が today より前のイベントは除外される（日付単位）。"""
        today = datetime(2026, 5, 15, 12, 0, tzinfo=JST)
        past = datetime(2026, 5, 14, 19, 0, tzinfo=JST)
        same_day_morning = datetime(2026, 5, 15, 9, 0, tzinfo=JST)
        future = datetime(2026, 5, 20, tzinfo=JST)
        feeds_iter = iter([
            _make_feed(
                self._entry("AWS past", "https://connpass.com/event/p/", published_dt=past),
                # 当日朝開始（午前 9 時）→ 日付単位なので残す
                self._entry("AWS today morning", "https://connpass.com/event/t/",
                            published_dt=same_day_morning),
                self._entry("AWS future", "https://connpass.com/event/f/", published_dt=future),
            ),
            _make_feed(),
            _make_feed(),
        ])

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        urls = sorted(e["event_url"] for e in events)
        self.assertEqual(urls, [
            "https://connpass.com/event/f/",
            "https://connpass.com/event/t/",
        ])

    def test_filters_events_without_started_at(self):
        """started_at が無いイベントはカレンダー表示できないため除外される。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        feeds_iter = iter([
            _make_feed(
                self._entry("AWS no-date", "https://connpass.com/event/n/"),
            ),
            _make_feed(),
            _make_feed(),
        ])

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        self.assertEqual(events, [])

    def test_sorts_by_started_at_ascending(self):
        """イベントは開催日時の昇順でソートされる。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        d1 = datetime(2026, 5, 18, tzinfo=JST)
        d2 = datetime(2026, 5, 25, tzinfo=JST)
        feeds_iter = iter([
            _make_feed(
                self._entry("AWS later", "https://connpass.com/event/L/", published_dt=d2),
                self._entry("AWS earlier", "https://connpass.com/event/E/", published_dt=d1),
            ),
            _make_feed(),
            _make_feed(),
        ])

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        self.assertEqual([e["event_url"] for e in events], [
            "https://connpass.com/event/E/",
            "https://connpass.com/event/L/",
        ])

    def test_filters_non_connpass_event_urls(self):
        """connpass の /event/ 配下以外の URL を持つエントリは除外される（SSRF/表示崩れ対策）。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        future = datetime(2026, 5, 20, tzinfo=JST)
        feeds_iter = iter([
            _make_feed(
                self._entry("AWS evil", "https://evilconnpass.com/event/1/", published_dt=future),
                self._entry("AWS http", "http://connpass.com/event/2/", published_dt=future),
                self._entry("AWS search", "https://connpass.com/search/", published_dt=future),
                self._entry("AWS ok", "https://connpass.com/event/3/", published_dt=future),
            ),
            _make_feed(),
            _make_feed(),
        ])

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        self.assertEqual(
            [e["event_url"] for e in events],
            ["https://connpass.com/event/3/"],
        )

    def test_continues_when_one_request_fails(self):
        """1 つの RSS 取得が失敗しても他の系統から取得継続する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        future = datetime(2026, 5, 20, tzinfo=JST)
        # 1 回目（東京）は例外、残りは成功
        call_count = {"n": 0}

        def fake_get(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated failure")
            return _make_response()

        feeds_iter = iter([
            _make_feed(
                self._entry("AWS k", "https://connpass.com/event/k/", published_dt=future),
            ),
            _make_feed(
                self._entry("AWS o", "https://connpass.com/event/o/", published_dt=future),
            ),
        ])

        with patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: next(feeds_iter)):
            events = fetch_events(today)

        urls = sorted(e["event_url"] for e in events)
        self.assertEqual(urls, [
            "https://connpass.com/event/k/",
            "https://connpass.com/event/o/",
        ])

    def test_raises_when_all_requests_fail(self):
        """全 RSS 取得が失敗した場合、events.json を空で上書きしないため例外を送出する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)

        def fake_get(*args, **kwargs):
            raise RuntimeError("simulated total outage")

        with patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("generate_events_calendar.feedparser.parse", side_effect=lambda c: _make_feed()):
            with self.assertRaises(RuntimeError) as cm:
                fetch_events(today)

        self.assertIn("全", str(cm.exception))

    def test_raises_when_all_feeds_fail_to_parse(self):
        """全 RSS が feedparser で bozo 扱い & entries 空 → 例外送出。"""
        today = datetime(2026, 5, 15, tzinfo=JST)

        def make_bozo_feed():
            f = MagicMock()
            f.entries = []
            f.bozo = True
            f.bozo_exception = Exception("malformed RSS")
            return f

        with patch("generate_events_calendar.requests.get", return_value=_make_response()), \
              patch("generate_events_calendar.feedparser.parse",
                   side_effect=lambda c: make_bozo_feed()):
            with self.assertRaises(RuntimeError):
                fetch_events(today)

    def test_uses_api_with_api_key(self):
        """CONNPASS_API_KEY が設定されている場合は connpass v2 API を利用する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        started = "2026-05-20T10:00:00+09:00"
        captured_requests: list[dict] = []
        responses = iter([
            _make_api_response([{
                "title": "AWS 勉強会",
                "url": "https://connpass.com/event/200/",
                "catch": "AWS hands-on",
                "started_at": started,
            }]),
            _make_api_response([{
                "title": "Kubernetes 勉強会",
                "url": "https://connpass.com/event/201/",
                "catch": "k8s",
                "started_at": started,
            }]),
            _make_api_response([{
                "title": "Python オンライン",
                "url": "https://connpass.com/event/202/",
                "catch": "python",
                "started_at": started,
            }]),
        ])

        def fake_get(*args, **kwargs):
            captured_requests.append({"args": args, "kwargs": kwargs})
            return next(responses)

        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}), \
             patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("generate_events_calendar.feedparser.parse") as feedparser_parse:
            events = fetch_events(today)

        self.assertEqual(len(events), 3)
        first_request = captured_requests[0]
        self.assertEqual(first_request["args"][0], "https://connpass.com/api/v2/events/")
        self.assertIn("headers", first_request["kwargs"])
        self.assertIn("params", first_request["kwargs"])
        self.assertEqual(first_request["kwargs"]["headers"].get("X-API-Key"), "test-key")
        self.assertEqual(first_request["kwargs"]["params"].get("count"), 100)
        self.assertEqual(first_request["kwargs"]["params"].get("order"), 2)
        self.assertFalse(first_request["kwargs"].get("allow_redirects", True))
        feedparser_parse.assert_not_called()

    def test_api_fetch_paginates_with_start_param(self):
        """v2 API は start を進めて複数ページ取得できる。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        started = "2026-05-20T10:00:00+09:00"
        captured_requests: list[dict] = []
        first_page_events = [
            {
                "title": f"AWS 東京 {i}",
                "url": f"https://connpass.com/event/{21000 + i}/",
                "catch": "aws",
                "started_at": started,
            }
            for i in range(100)
        ]

        def fake_get(*args, **kwargs):
            captured_requests.append({"args": args, "kwargs": kwargs})
            params = kwargs["params"]
            keyword = params.get("keyword")
            start = params.get("start")
            if keyword == "東京都" and start == 1:
                return _make_api_response(
                    first_page_events,
                    results_returned=100,
                    results_available=101,
                )
            if keyword == "東京都" and start == 101:
                return _make_api_response(
                    [{
                        "title": "AWS 東京 101",
                        "url": "https://connpass.com/event/21101/",
                        "catch": "aws",
                        "started_at": started,
                    }],
                    results_returned=1,
                    results_available=101,
                )
            if keyword in ("神奈川県", "オンライン"):
                return _make_api_response([], results_returned=0, results_available=0)
            raise AssertionError(f"unexpected params: {params}")

        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}), \
             patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("builtins.print") as mock_print:
            events = fetch_events(today)

        self.assertEqual(len(events), 101)
        tokyo_requests = [
            req for req in captured_requests
            if req["kwargs"]["params"].get("keyword") == "東京都"
        ]
        self.assertEqual(
            [req["kwargs"]["params"].get("start") for req in tokyo_requests],
            [1, 101],
        )
        self.assertFalse(
            any(
                "形式が不正" in (call.args[0] if call.args else "")
                for call in mock_print.call_args_list
            )
        )

    def test_api_fetch_keeps_pagination_when_metadata_is_missing(self):
        """results_* が欠落していても count 到達時は次ページを取得する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        started = "2026-05-20T10:00:00+09:00"
        captured_requests: list[dict] = []
        first_page_events = [
            {
                "title": f"AWS 東京 {i}",
                "url": f"https://connpass.com/event/{22000 + i}/",
                "catch": "aws",
                "started_at": started,
            }
            for i in range(100)
        ]

        def fake_get(*args, **kwargs):
            captured_requests.append({"args": args, "kwargs": kwargs})
            params = kwargs["params"]
            keyword = params.get("keyword")
            start = params.get("start")
            if keyword == "東京都" and start == 1:
                return _make_api_response(first_page_events)
            if keyword == "東京都" and start == 101:
                return _make_api_response([{
                    "title": "AWS 東京 101",
                    "url": "https://connpass.com/event/22101/",
                    "catch": "aws",
                    "started_at": started,
                }])
            if keyword in ("神奈川県", "オンライン"):
                return _make_api_response([])
            raise AssertionError(f"unexpected params: {params}")

        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}), \
             patch("generate_events_calendar.requests.get", side_effect=fake_get):
            events = fetch_events(today)

        self.assertEqual(len(events), 101)
        tokyo_requests = [
            req for req in captured_requests
            if req["kwargs"]["params"].get("keyword") == "東京都"
        ]
        self.assertEqual(
            [req["kwargs"]["params"].get("start") for req in tokyo_requests],
            [1, 101],
        )

    def test_api_fetch_keeps_pagination_when_metadata_is_bool(self):
        """results_* が bool でも不正値として扱い、count 到達時は次ページを取得する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        started = "2026-05-20T10:00:00+09:00"
        captured_requests: list[dict] = []
        first_page_events = [
            {
                "title": f"AWS 東京 {i}",
                "url": f"https://connpass.com/event/{22500 + i}/",
                "catch": "aws",
                "started_at": started,
            }
            for i in range(100)
        ]

        def fake_get(*args, **kwargs):
            captured_requests.append({"args": args, "kwargs": kwargs})
            params = kwargs["params"]
            keyword = params.get("keyword")
            start = params.get("start")
            if keyword == "東京都" and start == 1:
                return _make_api_response(
                    first_page_events,
                    results_returned=True,
                    results_available=True,
                )
            if keyword == "東京都" and start == 101:
                return _make_api_response([{
                    "title": "AWS 東京 101",
                    "url": "https://connpass.com/event/22601/",
                    "catch": "aws",
                    "started_at": started,
                }])
            if keyword in ("神奈川県", "オンライン"):
                return _make_api_response([])
            raise AssertionError(f"unexpected params: {params}")

        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}), \
             patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("builtins.print") as mock_print:
            events = fetch_events(today)

        self.assertEqual(len(events), 101)
        tokyo_requests = [
            req for req in captured_requests
            if req["kwargs"]["params"].get("keyword") == "東京都"
        ]
        self.assertEqual(
            [req["kwargs"]["params"].get("start") for req in tokyo_requests],
            [1, 101],
        )
        self.assertTrue(
            any(
                "results_returned の形式が不正 (bool)"
                in (call.args[0] if call.args else "")
                for call in mock_print.call_args_list
            )
        )
        self.assertTrue(
            any(
                "results_available の形式が不正 (bool)"
                in (call.args[0] if call.args else "")
                for call in mock_print.call_args_list
            )
        )

    def test_api_fetch_stops_early_when_event_limit_nearby(self):
        """収集件数が上限付近なら追加ページ取得を打ち切る。"""
        started = "2026-05-20T10:00:00+09:00"
        requests_calls: list[dict] = []
        page_events = [
            {
                "title": f"AWS 東京 {i}",
                "url": f"https://connpass.com/event/{23000 + i}/",
                "catch": "aws",
                "started_at": started,
            }
            for i in range(100)
        ]

        def fake_get(*args, **kwargs):
            requests_calls.append({"args": args, "kwargs": kwargs})
            return _make_api_response(
                page_events,
                results_returned=100,
                results_available=300,
            )

        with patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("generate_events_calendar.MAX_CALENDAR_EVENTS", 50), \
             patch("generate_events_calendar.CONNPASS_API_EARLY_STOP_BUFFER", 10):
            events, ok = _fetch_api_events(
                params={"keyword": "東京都", "ym": "202605"},
                place="東京都",
                today_str="2026/05/01",
                seen_urls=set(),
                label="東京都 202605",
                api_key="test-key",
            )

        self.assertTrue(ok)
        self.assertEqual(len(events), 100)
        self.assertEqual(len(requests_calls), 1)

    def test_api_fetch_fails_when_first_page_payload_is_not_dict(self):
        """1ページ目の JSON が dict 以外なら取得失敗として返す。"""
        response = _make_response()
        response.json = MagicMock(return_value=["unexpected"])

        with patch("generate_events_calendar.requests.get", return_value=response):
            events, ok = _fetch_api_events(
                params={"keyword": "東京都", "ym": "202605"},
                place="東京都",
                today_str="2026/05/01",
                seen_urls=set(),
                label="東京都 202605",
                api_key="test-key",
            )

        self.assertFalse(ok)
        self.assertEqual(events, [])

    def test_api_fetch_stops_additional_pages_when_events_is_not_list(self):
        """2ページ目以降の events 型不正は追加取得のみ打ち切る。"""
        started = "2026-05-20T10:00:00+09:00"
        requests_calls: list[dict] = []

        first_page = _make_api_response(
            [{
                "title": "AWS 東京 1",
                "url": "https://connpass.com/event/25001/",
                "catch": "aws",
                "started_at": started,
            }],
            results_returned=1,
            results_available=2,
        )
        second_page = _make_response()
        second_page.json = MagicMock(return_value={"events": "not-a-list"})
        responses = iter([first_page, second_page])

        def fake_get(*args, **kwargs):
            requests_calls.append({"args": args, "kwargs": kwargs})
            return next(responses)

        with patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("generate_events_calendar.CONNPASS_API_FETCH_COUNT", 1):
            events, ok = _fetch_api_events(
                params={"keyword": "東京都", "ym": "202605"},
                place="東京都",
                today_str="2026/05/01",
                seen_urls=set(),
                label="東京都 202605",
                api_key="test-key",
            )

        self.assertTrue(ok)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(requests_calls), 2)

    def test_api_fetch_skips_invalid_event_items(self):
        """events 内の不正要素（非 dict / 非文字列 URL）はスキップする。"""
        started = "2026-05-20T10:00:00+09:00"
        response = _make_api_response([
            ["not", "dict"],
            {
                "title": "AWS invalid url type",
                "url": 12345,
                "catch": "aws",
                "started_at": started,
            },
            {
                "title": 123,
                "url": "https://connpass.com/event/25002/",
                "catch": "aws",
                "started_at": started,
            },
            {
                "title": "AWS 正常",
                "url": "https://connpass.com/event/25003/",
                "catch": "aws",
                "started_at": started,
            },
        ])

        with patch("generate_events_calendar.requests.get", return_value=response):
            events, ok = _fetch_api_events(
                params={"keyword": "東京都", "ym": "202605"},
                place="東京都",
                today_str="2026/05/01",
                seen_urls=set(),
                label="東京都 202605",
                api_key="test-key",
            )

        self.assertTrue(ok)
        self.assertEqual(len(events), 2)
        self.assertEqual(
            [ev["event_url"] for ev in events],
            [
                "https://connpass.com/event/25002/",
                "https://connpass.com/event/25003/",
            ],
        )

    def test_fetch_events_stops_global_api_search_after_limit(self):
        """API 利用時は上限付近到達後に以降の検索を打ち切る。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        call_labels: list[str] = []

        def fake_fetch_api_events(*, params, place, today_str, seen_urls, label, api_key):
            # 実装シグネチャ互換のため受け取る（本テストでは未使用）。
            _ = (params, today_str, api_key)
            call_labels.append(label)
            idx = len(call_labels)
            url = f"https://connpass.com/event/{24000 + idx}/"
            seen_urls.add(url)
            return (
                [{
                    "title": f"AWS event {idx}",
                    "event_url": url,
                    "started_at": "2026/05/20 10:00",
                    "place": place,
                    "catch": "aws",
                }],
                True,
            )

        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}), \
             patch("generate_events_calendar._fetch_api_events", side_effect=fake_fetch_api_events), \
             patch("generate_events_calendar._enrich_descriptions"), \
             patch("generate_events_calendar.MAX_CALENDAR_EVENTS", 2), \
             patch("generate_events_calendar.CONNPASS_API_EARLY_STOP_BUFFER", 0):
            events = fetch_events(today)

        self.assertEqual(len(events), 2)
        self.assertEqual(call_labels, ["東京都 202605", "神奈川県 202605"])


class TestApiDescriptionExtraction(unittest.TestCase):
    """connpass v2 API の description フィールド取得に関するテスト"""

    def setUp(self):
        # テスト中の RSS 取得回数を抑えるため lookahead を 0 か月にする
        lookahead_patcher = patch("generate_events_calendar.CALENDAR_LOOKAHEAD_MONTHS", 0)
        self.addCleanup(lookahead_patcher.stop)
        lookahead_patcher.start()
        # ベンダーイベント取得はスキップ
        vendor_patcher = patch(
            "generate_events_calendar.fetch_vendor_news_events", return_value=[]
        )
        self.addCleanup(vendor_patcher.stop)
        vendor_patcher.start()

    def _make_api_event(self, title, url, catch="", description=None, started_at="2026-05-20T10:00:00+09:00"):
        ev: dict = {
            "title": title,
            "url": url,
            "catch": catch,
            "started_at": started_at,
        }
        if description is not None:
            ev["description"] = description
        return ev

    def test_api_description_stored_in_event(self):
        """API レスポンスの description フィールドが event dict に保存される。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        event_desc_html = "<p>Python勉強会の詳しい説明です。クラウドやAWSについて学びます。</p>"
        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}):
            resp = _make_api_response([self._make_api_event(
                "Python 勉強会",
                "https://connpass.com/event/300/",
                catch="python",
                description=event_desc_html,
            )])
            responses = iter([resp, _make_api_response([]), _make_api_response([])])
            with patch("generate_events_calendar.requests.get", side_effect=lambda *a, **kw: next(responses)), \
                 patch("generate_events_calendar._enrich_descriptions") as mock_enrich:
                events = fetch_events(today)

        self.assertEqual(len(events), 1)
        self.assertIn("description", events[0])
        self.assertIn("Python勉強会の詳しい説明", events[0]["description"])
        self.assertNotIn("<p>", events[0]["description"])

    def test_api_no_description_field_no_key_in_event(self):
        """API レスポンスに description がない場合、event dict に description キーは入らない。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}):
            resp = _make_api_response([self._make_api_event(
                "Python 勉強会",
                "https://connpass.com/event/301/",
                catch="python",
            )])
            responses = iter([resp, _make_api_response([]), _make_api_response([])])
            with patch("generate_events_calendar.requests.get", side_effect=lambda *a, **kw: next(responses)), \
                 patch("generate_events_calendar._enrich_descriptions"):
                events = fetch_events(today)

        self.assertEqual(len(events), 1)
        self.assertNotIn("description", events[0])

    def test_api_description_used_for_it_event_filter(self):
        """IT キーワードが catch にはなく description にある場合もフィルタを通過する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        desc_html = "<p>このイベントではKubernetesとDockerについて学びます。</p>"
        with patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}):
            resp = _make_api_response([self._make_api_event(
                "コンテナ技術勉強会",
                "https://connpass.com/event/302/",
                catch="",  # catch にキーワードなし
                description=desc_html,  # description にキーワードあり
            )])
            responses = iter([resp, _make_api_response([]), _make_api_response([])])
            with patch("generate_events_calendar.requests.get", side_effect=lambda *a, **kw: next(responses)), \
                 patch("generate_events_calendar._enrich_descriptions"):
                events = fetch_events(today)

        # Kubernetes/Docker キーワードが description にあるのでフィルタを通過する
        self.assertEqual(len(events), 1)
        self.assertIn("description", events[0])

    def test_enrich_skips_events_with_description(self):
        """description が既に設定されているイベントはページスクレイピングをスキップする。"""
        from generate_events_calendar import _enrich_descriptions
        events = [
            {
                "title": "AWS 勉強会",
                "event_url": "https://connpass.com/event/400/",
                "description": "既存の説明文",
            },
            {
                "title": "Python 勉強会",
                "event_url": "https://connpass.com/event/401/",
                # description なし
            },
        ]
        fetch_calls: list[str] = []

        def _fake_fetch(url: str) -> str:
            fetch_calls.append(url)
            return "ページから取得した説明"

        with patch("generate_events_calendar._fetch_event_description", side_effect=_fake_fetch):
            _enrich_descriptions(events)

        # description が既にあるイベントはスキップされ、ないものだけスクレイピング対象
        self.assertEqual(len(fetch_calls), 1)
        self.assertIn("event/401", fetch_calls[0])
        self.assertEqual(events[0]["description"], "既存の説明文")
        self.assertIn("ページから取得した説明", events[1].get("description", ""))


class TestMain(unittest.TestCase):
    """main() のテスト"""

    def test_main_does_not_fail_workflow_on_fetch_runtime_error(self):
        """fetch_events が RuntimeError の場合でも非 0 終了しない。"""
        with patch("generate_events_calendar.fetch_events", side_effect=RuntimeError("total failure")), \
             patch("generate_events_calendar.Path.write_text") as write_text:
            main()
        write_text.assert_not_called()

    def test_main_writes_empty_events_without_error(self):
        """イベント0件でも events.json を正常に書き出す。"""
        with patch("generate_events_calendar.fetch_events", return_value=[]), \
             patch("generate_events_calendar.Path.write_text") as write_text:
            main()
        write_text.assert_called_once()
        written = write_text.call_args.args[0]
        self.assertIn('"events": []', written)


# ---------------------------------------------------------------------------
# fetch_vendor_news_events
# ---------------------------------------------------------------------------

class TestFetchVendorNewsEvents(unittest.TestCase):
    """fetch_vendor_news_events() のテスト（requests / feedparser はモック）"""

    def _entry(self, title: str, link: str, summary: str = "カンファレンス情報",
               published_dt: datetime | None = None) -> dict:
        e: dict = {"title": title, "link": link, "summary": summary}
        if published_dt is not None:
            utc = published_dt.astimezone(timezone.utc)
            e["published_parsed"] = (
                utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second, 0, 0, 0
            )
        return e

    def test_returns_vendor_events_with_correct_fields(self):
        """ベンダーイベントが title / event_url / started_at / place / vendor_event フィールドを持つ。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        pub = datetime(2026, 5, 10, 9, 0, tzinfo=JST)
        feed = _make_feed(
            self._entry("Microsoft Build 2026 開催", "https://news.google.com/article/1", published_dt=pub),
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {"name": "Microsoft Build", "url": "https://news.google.com/rss/dummy", "place": "Seattle / オンライン"},
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIn("Microsoft Build", ev["title"])
        self.assertEqual(ev["event_url"], "https://news.google.com/article/1")
        self.assertTrue(ev["started_at"].startswith("2026/05/10"))
        self.assertEqual(ev["place"], "Seattle / オンライン")
        self.assertTrue(ev.get("vendor_event"))

    def test_skips_entries_without_published_date(self):
        """published_parsed がないエントリはスキップされる。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        feed = _make_feed(
            # published_dt なし → started_at が空 → スキップ
            {"title": "AWS Summit Japan 2026 開催決定", "link": "https://news.google.com/article/2", "summary": "AWS"},
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {"name": "AWS Summit Japan", "url": "https://news.google.com/rss/dummy", "place": "東京"},
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        self.assertEqual(events, [])

    def test_deduplicates_urls_across_feeds(self):
        """同一 URL が複数フィードで現れた場合、2 件目以降はスキップされる。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        pub = datetime(2026, 5, 12, 10, 0, tzinfo=JST)
        shared_url = "https://news.google.com/article/dup"
        feed = _make_feed(
            self._entry("重複記事", shared_url, published_dt=pub),
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {"name": "Feed A", "url": "https://news.google.com/rss/a", "place": "オンライン"},
            {"name": "Feed B", "url": "https://news.google.com/rss/b", "place": "オンライン"},
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        urls = [e["event_url"] for e in events]
        self.assertEqual(urls.count(shared_url), 1)

    def test_continues_on_request_failure(self):
        """1 つのフィード取得が失敗しても他フィードの取得を継続する。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        pub = datetime(2026, 5, 14, 9, 0, tzinfo=JST)

        def fake_get(url, *args, **kwargs):
            if "fail" in url:
                raise RuntimeError("simulated failure")
            return _make_response()

        feed = _make_feed(
            self._entry("KubeCon 2026", "https://news.google.com/article/k", published_dt=pub),
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {"name": "Fail Feed", "url": "https://news.google.com/rss/fail", "place": "現地"},
            {"name": "KubeCon", "url": "https://news.google.com/rss/kubecon", "place": "現地 / オンライン"},
        ]), \
             patch("generate_events_calendar.requests.get", side_effect=fake_get), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        # 2 つ目のフィードから 1 件取得できていること
        self.assertEqual(len(events), 1)
        self.assertIn("KubeCon", events[0]["title"])

    def test_respects_max_entries_per_feed(self):
        """フィードごとの最大取得件数（_VENDOR_EVENT_MAX_ENTRIES_PER_FEED）を超えない。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        pub = datetime(2026, 5, 10, tzinfo=JST)
        # 最大件数 + 2 件のエントリを用意
        from generate_events_calendar import _VENDOR_EVENT_MAX_ENTRIES_PER_FEED
        entries = [
            self._entry(f"Article {i}", f"https://news.google.com/article/{i}", published_dt=pub)
            for i in range(_VENDOR_EVENT_MAX_ENTRIES_PER_FEED + 2)
        ]
        feed = _make_feed(*entries)

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {"name": "Google Cloud Next", "url": "https://news.google.com/rss/gcn", "place": "オンライン"},
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        self.assertLessEqual(len(events), _VENDOR_EVENT_MAX_ENTRIES_PER_FEED)

    def test_vendor_events_included_in_fetch_events(self):
        """fetch_events() がベンダーイベントを含む結果を返す。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        future = datetime(2026, 5, 20, 19, 0, tzinfo=JST)
        pub = datetime(2026, 5, 14, 9, 0, tzinfo=JST)

        connpass_feed = _make_feed(
            self._entry("AWS 勉強会", "https://connpass.com/event/99/",
                        summary="AWS hands-on", published_dt=future),
        )
        vendor_event = {
            "title": "[Microsoft Build] Build 2026 発表",
            "event_url": "https://news.google.com/article/build",
            "started_at": "2026/05/14 09:00",
            "place": "Seattle / オンライン",
            "catch": "新発表",
            "vendor_event": True,
        }

        with patch("generate_events_calendar.CALENDAR_LOOKAHEAD_MONTHS", 0), \
             patch("generate_events_calendar._enrich_descriptions", lambda ev: None), \
             patch("generate_events_calendar.fetch_vendor_news_events", return_value=[vendor_event]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=connpass_feed):
            events = fetch_events(today)

        urls = [e["event_url"] for e in events]
        self.assertIn("https://connpass.com/event/99/", urls)
        self.assertIn("https://news.google.com/article/build", urls)
        # ベンダーイベントに vendor_event フラグが付いていること
        vendor = next(e for e in events if e["event_url"] == "https://news.google.com/article/build")
        self.assertTrue(vendor.get("vendor_event"))

    def test_skips_articles_older_than_lookback(self):
        """VENDOR_EVENT_LOOKBACK_DAYS より前の記事はデフォルトフィードから除外される。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        # ルックバック期間より 1 日前 → 除外されるべき
        old_pub = today - timedelta(days=VENDOR_EVENT_LOOKBACK_DAYS + 1)
        # ルックバック期間内 → 含まれるべき
        recent_pub = today - timedelta(days=VENDOR_EVENT_LOOKBACK_DAYS - 1)

        feed = _make_feed(
            self._entry("Old Summit 参加レポート", "https://news.google.com/article/old", published_dt=old_pub),
            self._entry("Recent Summit 2026 開催", "https://news.google.com/article/recent", published_dt=recent_pub),
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {"name": "Test Summit", "url": "https://news.google.com/rss/test", "place": "東京"},
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        urls = [e["event_url"] for e in events]
        self.assertNotIn("https://news.google.com/article/old", urls,
                         "ルックバック期間より前の記事はカレンダーに含まれてはいけない")
        self.assertIn("https://news.google.com/article/recent", urls,
                      "ルックバック期間内の記事はカレンダーに含まれるべき")

    def test_per_feed_lookback_days_includes_older_articles(self):
        """lookback_days が設定されたフィードはその日数内の記事を含む。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        # VENDOR_EVENT_LOOKBACK_DAYS(30日)より前だが VENDOR_REPORT_LOOKBACK_DAYS(90日)以内
        old_pub = today - timedelta(days=VENDOR_EVENT_LOOKBACK_DAYS + 10)  # 40日前

        feed = _make_feed(
            self._entry(
                "AWS re:Invent 参加レポート",
                "https://news.google.com/article/report",
                published_dt=old_pub,
            ),
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {
                "name": "AWS re:Invent 参加レポート",
                "url": "https://news.google.com/rss/test",
                "place": "Las Vegas / オンライン",
                "lookback_days": VENDOR_REPORT_LOOKBACK_DAYS,
            },
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        urls = [e["event_url"] for e in events]
        self.assertIn("https://news.google.com/article/report", urls,
                      "lookback_days 内の記事はカレンダーに含まれるべき")

    def test_per_feed_lookback_days_excludes_articles_beyond_custom_window(self):
        """lookback_days を超えた記事はフィード個別の設定でも除外される。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        # VENDOR_REPORT_LOOKBACK_DAYS(90日)より 1 日前 → 除外されるべき
        too_old_pub = today - timedelta(days=VENDOR_REPORT_LOOKBACK_DAYS + 1)

        feed = _make_feed(
            self._entry(
                "Google I/O 2025 参加レポート",
                "https://news.google.com/article/old_report",
                published_dt=too_old_pub,
            ),
        )

        with patch("generate_events_calendar.VENDOR_EVENT_NEWS_FEEDS", [
            {
                "name": "Google I/O 参加レポート",
                "url": "https://news.google.com/rss/test",
                "place": "Mountain View / オンライン",
                "lookback_days": VENDOR_REPORT_LOOKBACK_DAYS,
            },
        ]), \
             patch("generate_events_calendar.requests.get", return_value=_make_response()), \
             patch("generate_events_calendar.feedparser.parse", return_value=feed):
            events = fetch_vendor_news_events(today)

        urls = [e["event_url"] for e in events]
        self.assertNotIn("https://news.google.com/article/old_report", urls,
                         "lookback_days を超えた記事はカレンダーに含まれてはいけない")

    def test_vendor_report_lookback_days_is_greater_than_default(self):
        """VENDOR_REPORT_LOOKBACK_DAYS は VENDOR_EVENT_LOOKBACK_DAYS より大きい。"""
        self.assertGreater(VENDOR_REPORT_LOOKBACK_DAYS, VENDOR_EVENT_LOOKBACK_DAYS)

    def test_participation_report_feeds_have_lookback_days(self):
        """参加レポートフィードには lookback_days が設定されていること。"""
        report_feeds = [f for f in VENDOR_EVENT_NEWS_FEEDS if "参加レポート" in f["name"]]
        self.assertGreater(len(report_feeds), 0, "参加レポートフィードが 1 件以上あること")
        for feed in report_feeds:
            self.assertIn("lookback_days", feed,
                          f"{feed['name']} に 'lookback_days' がない")
            self.assertEqual(feed["lookback_days"], VENDOR_REPORT_LOOKBACK_DAYS,
                             f"{feed['name']} の lookback_days が VENDOR_REPORT_LOOKBACK_DAYS と一致しない")

    def test_vendor_events_list_not_empty(self):
        """VENDOR_EVENT_NEWS_FEEDS が空でないこと（設定漏れ防止）。"""
        self.assertGreater(len(VENDOR_EVENT_NEWS_FEEDS), 0)

    def test_vendor_events_feeds_have_required_keys(self):
        """各フィードエントリに name / url / place が含まれること。"""
        for feed in VENDOR_EVENT_NEWS_FEEDS:
            self.assertIn("name", feed, f"{feed} に 'name' がない")
            self.assertIn("url", feed, f"{feed} に 'url' がない")
            self.assertIn("place", feed, f"{feed} に 'place' がない")


if __name__ == "__main__":
    unittest.main()
