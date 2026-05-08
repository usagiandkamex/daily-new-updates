"""
generate_events_calendar.py の純粋ロジックの単体テスト

外部 HTTP 通信は unittest.mock でスタブし、実際のネットワーク接続は行わない。
"""

import sys
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_events_calendar import (
    _build_search_months,
    _is_it_event,
    _ConnpassEventPageParser,
    _is_connpass_event_url,
    _truncate_description,
    fetch_events,
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
        feedparser_parse.assert_not_called()

    def test_api_fetch_paginates_with_start_param(self):
        """v2 API は start を進めて複数ページ取得できる。"""
        today = datetime(2026, 5, 15, tzinfo=JST)
        started = "2026-05-20T10:00:00+09:00"
        captured_requests: list[dict] = []

        def fake_get(*args, **kwargs):
            captured_requests.append({"args": args, "kwargs": kwargs})
            params = kwargs["params"]
            keyword = params.get("keyword")
            start = params.get("start")
            if keyword == "東京都" and start == 1:
                return _make_api_response(
                    [{
                        "title": "AWS 東京 1",
                        "url": "https://connpass.com/event/210/",
                        "catch": "aws",
                        "started_at": started,
                    }],
                    results_returned=100,
                    results_available=101,
                )
            if keyword == "東京都" and start == 101:
                return _make_api_response(
                    [{
                        "title": "AWS 東京 2",
                        "url": "https://connpass.com/event/211/",
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
             patch("generate_events_calendar.requests.get", side_effect=fake_get):
            events = fetch_events(today)

        self.assertEqual(
            sorted(e["event_url"] for e in events),
            ["https://connpass.com/event/210/", "https://connpass.com/event/211/"],
        )
        tokyo_requests = [
            req for req in captured_requests
            if req["kwargs"]["params"].get("keyword") == "東京都"
        ]
        self.assertEqual(
            [req["kwargs"]["params"].get("start") for req in tokyo_requests],
            [1, 101],
        )


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


if __name__ == "__main__":
    unittest.main()
