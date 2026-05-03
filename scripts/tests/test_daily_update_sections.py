"""
generate_daily_update.py のセッション分割（セクションごと個別 LLM 呼び出し）ロジックのテスト
"""

import sys
import os
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

# スクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import generate_daily_update as du
import article_generator_shared as ags


def _make_client(content: str = "生成テキスト"):
    """LLM クライアントのモックを作成する。"""
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    client.chat.completions.create.return_value.choices = [choice]
    return client


class TestBuildSectionPromptDailyUpdate(unittest.TestCase):
    """_build_section_prompt() のテスト"""

    def _get_section(self, key: str) -> dict:
        for s in du.SECTION_DEFINITIONS:
            if s["key"] == key:
                return s
        raise KeyError(key)

    def test_list_data_uses_data_label(self):
        """list 型データの場合、section_def['data_label'] がプロンプトに含まれる。"""
        section = self._get_section("azure")
        data = [{"title": "テスト記事", "url": "https://example.com"}]
        prompt = du._build_section_prompt(section, data)
        self.assertIn(section["data_label"], prompt)
        self.assertIn("テスト記事", prompt)

    def test_dict_data_uses_keys_as_labels(self):
        """dict 型データの場合、各キーがセクションラベルとしてプロンプトに含まれる。"""
        section = self._get_section("community")
        data = {
            "connpass イベント（東京・神奈川、申し込み受付中）": [{"title": "イベントA"}],
            "コミュニティイベント参加レポート": [{"title": "レポートB"}],
        }
        prompt = du._build_section_prompt(section, data)
        self.assertIn("connpass イベント（東京・神奈川、申し込み受付中）", prompt)
        self.assertIn("コミュニティイベント参加レポート", prompt)
        self.assertIn("イベントA", prompt)
        self.assertIn("レポートB", prompt)

    def test_empty_list_returns_prompt(self):
        """空データでもプロンプトが生成される。"""
        section = self._get_section("tech")
        prompt = du._build_section_prompt(section, [])
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)

    def test_instruction_included(self):
        """instruction テキストがプロンプトに含まれる。"""
        section = self._get_section("tech")
        prompt = du._build_section_prompt(section, [])
        self.assertIn(section["instruction"], prompt)


class TestGenerateSectionDailyUpdate(unittest.TestCase):
    """generate_section() のテスト"""

    def _get_section(self, key: str) -> dict:
        for s in du.SECTION_DEFINITIONS:
            if s["key"] == key:
                return s
        raise KeyError(key)

    def test_calls_llm_once_per_section(self):
        """generate_section は 1 セクションにつき LLM を 1 回だけ呼び出す。"""
        client = _make_client("## 1. Azureセクション")
        section = self._get_section("azure")
        data = [{"title": "記事1"}]
        result = du.generate_section(client, "gpt-4o", section, data)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(result, "## 1. Azureセクション")

    def test_empty_list_returns_no_info_message_without_llm(self):
        """空データの場合は LLM を呼ばずに「ありません」メッセージを返す。"""
        client = _make_client("呼ばれないはず")
        section = self._get_section("azure")
        result = du.generate_section(client, "gpt-4o", section, [])
        self.assertEqual(client.chat.completions.create.call_count, 0)
        self.assertIn(section["header"], result)
        self.assertIn("ありません", result)

    def test_empty_list_result_contains_section_header(self):
        """空データ時の戻り値にセクションヘッダーが含まれる（リスト型セクションのみ）。"""
        client = _make_client("呼ばれないはず")
        for section in du.SECTION_DEFINITIONS:
            # community セクションは dict 型データのため空リストの早期返却対象外
            if section["key"] == "community":
                continue
            result = du.generate_section(client, "gpt-4o", section, [])
            self.assertTrue(
                result.startswith(section["header"]),
                f"セクション {section['key']} の空データ結果がヘッダーで始まっていない",
            )

    def test_uses_section_system_prompt(self):
        """システムプロンプトにセクション固有のものが使われる。"""
        client = _make_client("出力")
        section = self._get_section("tech")
        du.generate_section(client, "gpt-4o", section, [{"title": "記事1"}])
        call_kwargs = client.chat.completions.create.call_args
        messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
        system_msg = next(m for m in messages if m["role"] == "system")
        self.assertEqual(system_msg["content"], section["system"])

    def test_max_tokens_is_section_output_limit(self):
        """max_tokens に SECTION_MAX_OUTPUT_TOKENS が使われる。"""
        client = _make_client("出力")
        section = self._get_section("business")
        du.generate_section(client, "gpt-4o", section, [{"title": "記事1"}])
        call_kwargs = client.chat.completions.create.call_args
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        self.assertEqual(kwargs.get("max_tokens"), du.SECTION_MAX_OUTPUT_TOKENS)

    def test_trims_list_when_prompt_too_large(self):
        """プロンプトが上限を超えた場合、データリストが削減される。"""
        section = self._get_section("azure")
        # max_input より大きくなるよう大量のデータを用意する
        big_item = {"title": "x" * 1000, "description": "y" * 1000}
        data = [dict(big_item) for _ in range(50)]
        original_len = len(data)

        client = _make_client("trimmed")
        du.generate_section(client, "gpt-4o", section, data)
        # データが削減されていることを確認
        self.assertLess(len(data), original_len)

    def test_stops_trimming_at_3_items(self):
        """データが3件以下になった場合はそれ以上削減しない。"""
        section = self._get_section("azure")
        # 意図的に上限を超える 3 件のデータ
        big_item = {"title": "x" * 5000, "description": "y" * 5000}
        data = [dict(big_item) for _ in range(3)]

        client = _make_client("output")
        du.generate_section(client, "gpt-4o", section, data)
        self.assertEqual(len(data), 3)


class TestGenerateArticleDailyUpdate(unittest.TestCase):
    """generate_article() のテスト（セッション分割）"""

    def test_calls_llm_once_per_section(self):
        """generate_article は データがある SECTION_DEFINITIONS の数だけ LLM を呼び出す。"""
        client = _make_client("セクション出力")
        result = du.generate_article(
            client, "gpt-4o", "20260401",
            azure_news=[{"title": "a"}],
            tech_news=[{"title": "b"}],
            business_news=[{"title": "c"}],
            sns_news=[{"title": "d"}],
            connpass_events=[{"title": "f"}],
            event_reports=[{"title": "g"}],
        )
        expected_calls = len(du.SECTION_DEFINITIONS)
        self.assertEqual(client.chat.completions.create.call_count, expected_calls)

    def test_article_starts_with_date_header(self):
        """記事の先頭に日付ヘッダーが含まれる。"""
        client = _make_client("セクション本文")
        result = du.generate_article(
            client, "gpt-4o", "20260401",
            azure_news=[],
            tech_news=[],
            business_news=[],
            sns_news=[],
            connpass_events=[],
            event_reports=[],
        )
        self.assertIn("# 2026/04/01 デイリーアップデート", result)

    def test_empty_list_sections_show_no_info_message(self):
        """空データの全セクションは「ありません」メッセージを含む。
        コミュニティセクションはハイブリッド生成（スクリプト）のためヘッダーも含まれる。
        """
        client = _make_client("コミュニティ出力")
        result = du.generate_article(
            client, "gpt-4o", "20260401",
            azure_news=[],
            tech_news=[],
            business_news=[],
            sns_news=[],
            connpass_events=[],
            event_reports=[],
        )
        # 全セクションのヘッダーが含まれること（コミュニティセクションはスクリプト生成）
        for section in du.SECTION_DEFINITIONS:
            self.assertIn(section["header"], result,
                          f"セクション {section['key']} のヘッダーが記事に含まれない")
        self.assertIn("ありません", result)

    def test_all_section_outputs_in_article(self):
        """各セクション出力が結合されて 1 つの記事になる。"""
        sections = du.SECTION_DEFINITIONS
        # セクションごとに異なるテキストを返すモックを作成
        client = MagicMock()
        responses = []
        for i, s in enumerate(sections):
            choice = MagicMock()
            choice.message.content = f"  section_{s['key']}_output  "
            mock_resp = MagicMock()
            mock_resp.choices = [choice]
            responses.append(mock_resp)
        client.chat.completions.create.side_effect = responses

        result = du.generate_article(
            client, "gpt-4o", "20260401",
            azure_news=[{"title": "a"}],
            tech_news=[{"title": "b"}],
            business_news=[{"title": "c"}],
            sns_news=[{"title": "d"}],
            connpass_events=[{"title": "f"}],
            event_reports=[{"title": "g"}],
        )
        for s in sections:
            self.assertIn(f"section_{s['key']}_output", result)

    def test_each_section_uses_independent_session(self):
        """各セクションが独立したシステムプロンプトで呼び出される（セッション分割の確認）。"""
        client = _make_client("出力")
        du.generate_article(
            client, "gpt-4o", "20260401",
            azure_news=[{"title": "a"}],
            tech_news=[{"title": "b"}],
            business_news=[{"title": "c"}],
            sns_news=[{"title": "d"}],
            connpass_events=[{"title": "f"}],
            event_reports=[{"title": "g"}],
        )
        # 呼び出しごとのシステムプロンプトを収集
        system_prompts = []
        for c in client.chat.completions.create.call_args_list:
            kwargs = c[1] if c[1] else {}
            msgs = kwargs.get("messages", [])
            sys_msg = next((m["content"] for m in msgs if m["role"] == "system"), None)
            system_prompts.append(sys_msg)

        # セクションごとに異なるシステムプロンプトが使われていることを確認
        unique_prompts = set(p for p in system_prompts if p)
        self.assertEqual(len(unique_prompts), len(du.SECTION_DEFINITIONS))


class TestSectionDefinitions(unittest.TestCase):
    """SECTION_DEFINITIONS の構造テスト"""

    def test_all_sections_have_required_keys(self):
        """各セクション定義に必須キーが存在する。"""
        required_keys = {"key", "system", "instruction", "header"}
        for section in du.SECTION_DEFINITIONS:
            for k in required_keys:
                self.assertIn(k, section, f"セクション {section.get('key')} に '{k}' がない")

    def test_section_keys_match_max_input_chars(self):
        """SECTION_MAX_INPUT_CHARS に全セクションキーのエントリが存在する。"""
        for section in du.SECTION_DEFINITIONS:
            self.assertIn(
                section["key"], du.SECTION_MAX_INPUT_CHARS,
                f"SECTION_MAX_INPUT_CHARS にキー '{section['key']}' がない"
            )

    def test_max_output_tokens_positive(self):
        """SECTION_MAX_OUTPUT_TOKENS は正の整数。"""
        self.assertIsInstance(du.SECTION_MAX_OUTPUT_TOKENS, int)
        self.assertGreater(du.SECTION_MAX_OUTPUT_TOKENS, 0)

    def test_instructions_enforce_heading_and_no_section_closing(self):
        """各 instruction に見出し非リンク・セクション締め禁止の指示が含まれる。"""
        for section in du.SECTION_DEFINITIONS:
            instruction = section["instruction"]
            self.assertIn("見出し（###）自体はハイパーリンクにせず", instruction)
            self.assertIn("締めの文章は入れないでください", instruction)


class TestConnpassEventFetchConfig(unittest.TestCase):
    """connpass イベント取得設定のテスト"""

    def test_api_fetch_count_greater_than_max_events(self):
        """API フェッチ件数は最終出力件数より大きい（フィルタリング余裕を確保）。"""
        self.assertGreater(du.CONNPASS_API_FETCH_COUNT, du.CONNPASS_MAX_EVENTS)

    def test_api_fetch_count_within_connpass_limit(self):
        """API フェッチ件数は connpass v2 API の上限（100）以内。"""
        self.assertLessEqual(du.CONNPASS_API_FETCH_COUNT, 100)

    def test_osaka_not_in_target_prefectures(self):
        """大阪府は対象都道府県に含まれない（東京・神奈川のみ）。"""
        self.assertNotIn("大阪府", du.CONNPASS_TARGET_PREFECTURES)

    def test_tokyo_and_kanagawa_in_target_prefectures(self):
        """東京都・神奈川県が引き続き対象都道府県に含まれる。"""
        self.assertIn("東京都", du.CONNPASS_TARGET_PREFECTURES)
        self.assertIn("神奈川県", du.CONNPASS_TARGET_PREFECTURES)

    def test_fetch_connpass_uses_ym(self):
        """CONNPASS_API_KEY が設定された場合、API に v2 公式の ym パラメータを送信する。

        connpass v2 API（https://connpass.com/about/api/v2/）の公式日付パラメータは
        ym (YYYYMM) と ymd (YYYYMMDD) のみ。v1 由来の started_at_gte 等は存在しないため
        使用しない。
        """
        captured_yms: list[str] = []
        captured_started_at_gte: list = []

        def fake_get(url, params=None, headers=None, timeout=None):
            params = params or {}
            # v2 API への呼び出しのみを対象（X-API-Key ヘッダーで判別）
            if headers and "X-API-Key" in headers:
                if "ym" in params:
                    captured_yms.append(params["ym"])
                if "started_at_gte" in params:
                    captured_started_at_gte.append(params["started_at_gte"])
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"events": [], "results_returned": 0}
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            du.fetch_connpass_events("20260501")

        # ym パラメータが送信され、対象月（202605）が含まれる
        self.assertTrue(captured_yms, "v2 API に ym パラメータが送信されていない")
        self.assertIn("202605", captured_yms)
        # 未文書の started_at_gte は送信されない
        self.assertEqual(
            captured_started_at_gte,
            [],
            "未文書の started_at_gte は v2 API に送信してはならない",
        )

    def test_fetch_connpass_uses_api_fetch_count(self):
        """CONNPASS_API_KEY が設定された場合、API に CONNPASS_API_FETCH_COUNT を送信する。"""
        captured_params: dict = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            # v2 API 呼び出しのみ対象
            if headers and "X-API-Key" in headers:
                captured_params.update(params or {})
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"events": [], "results_returned": 0}
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            du.fetch_connpass_events("20260501")

        self.assertEqual(captured_params.get("count"), du.CONNPASS_API_FETCH_COUNT)

    def test_rss_search_months_no_skip_on_month_end(self):
        """遡及 30 日の範囲で途中の月が欠落しない（3/1 → 1月・2月・3月が全て含まれる）。"""
        captured_yms: list[str] = []

        def fake_get(url, params=None, headers=None, timeout=None):
            if params and "ym" in params:
                captured_yms.append(params["ym"])
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            du._fetch_connpass_events_rss("20260301")

        # 3/1 から 30 日遡ると 1/30 → 1月・2月・3月が全て揃う
        unique_yms = sorted(set(captured_yms))
        self.assertIn("202601", unique_yms)
        self.assertIn("202602", unique_yms)
        self.assertIn("202603", unique_yms)

    def test_discover_event_keywords_always_includes_seed_keywords(self):
        """_discover_event_keywords_from_social() は常にシードキーワードを含む。"""
        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            result = du._discover_event_keywords_from_social()

        for seed in du._CONNPASS_COMMUNITY_SEED_KEYWORDS:
            self.assertIn(seed, result)

    def test_fetch_connpass_no_api_key_runs_multistep(self):
        """CONNPASS_API_KEY 未設定でも多段検索（RSS pref_id + オンライン + 段階3 キーワード RSS）が実行される。"""
        captured_pref_ids: list[int] = []
        captured_online_flags: list[int] = []

        def fake_get(url, params=None, headers=None, timeout=None):
            if params and "pref_id" in params:
                captured_pref_ids.append(params["pref_id"])
            if params and params.get("online") == 1:
                captured_online_flags.append(params["online"])
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            result = du.fetch_connpass_events("20260501")

        # 東京都（pref_id=13）・神奈川県（pref_id=14）が検索されている
        self.assertIn(du._CONNPASS_PREFECTURE_IDS["東京都"], captured_pref_ids)
        self.assertIn(du._CONNPASS_PREFECTURE_IDS["神奈川県"], captured_pref_ids)
        # オンラインイベント（online=1）も検索されている
        self.assertTrue(len(captured_online_flags) > 0)
        # 結果はリスト（空でも可）
        self.assertIsInstance(result, list)

    def test_rss_search_online_events_have_place_set(self):
        """オンライン検索（online=1）で取得したイベントの place は "オンライン" に設定される。"""
        online_calls: list[bool] = []

        def fake_get(url, params=None, headers=None, timeout=None):
            online_calls.append(bool(params and params.get("online") == 1))
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry_data = {
            "link": "https://connpass.com/event/999/",
            "title": "Python オンライン勉強会",
            "summary": "オンラインで Python を学ぶ",
        }

        def fake_parse(content):
            # オンライン検索（online_calls[-1] が True）のときだけエントリを返す
            if online_calls and online_calls[-1]:
                entry = MagicMock()
                entry.get.side_effect = lambda k, d="": entry_data.get(k, d)
                return MagicMock(entries=[entry])
            return MagicMock(entries=[])

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.side_effect = fake_parse
            result = du._fetch_connpass_events_rss("20260501")

        online_events = [e for e in result if e.get("place") == "オンライン"]
        self.assertTrue(len(online_events) > 0)

    def test_search_connpass_rss_by_keyword_deduplicates(self):
        """_search_connpass_rss_by_keyword() は seen_urls に登録済みの URL を除外する。"""
        existing_url = "https://connpass.com/event/123/"

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            entry = MagicMock()
            _entry_data = {
                "link": existing_url,
                "title": "Python 勉強会",
                "summary": "Python エンジニア向け",
            }
            entry.get.side_effect = lambda k, d="": _entry_data.get(k, d)
            mock_fp.parse.return_value = MagicMock(entries=[entry])

            seen: set[str] = {existing_url}
            result = du._search_connpass_rss_by_keyword("Python", ["202605"], seen)

        # 既登録 URL は返却リストに含まれない
        self.assertEqual(result, [])

    def test_parse_rss_event_started_at_returns_formatted_datetime(self):
        """_parse_rss_event_started_at() は published_parsed から開催日時文字列を返す。"""
        import time
        entry = MagicMock()
        # 2026-06-15 10:00:00 UTC → JST は 2026-06-15 19:00:00
        pub = time.strptime("2026-06-15 10:00:00", "%Y-%m-%d %H:%M:%S")
        entry.get.side_effect = lambda k, d=None: {"published_parsed": pub}.get(k, d)
        result = du._parse_rss_event_started_at(entry)
        self.assertEqual(result, "2026/06/15 19:00")

    def test_parse_rss_event_started_at_returns_empty_when_no_date(self):
        """_parse_rss_event_started_at() は published_parsed がない場合に空文字列を返す。"""
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: None
        result = du._parse_rss_event_started_at(entry)
        self.assertEqual(result, "")

    def test_rss_events_populate_started_at_from_published_parsed(self):
        """connpass RSS 取得イベントの started_at は published_parsed から設定される。"""
        import time

        # 2026-05-10 10:00:00 UTC
        pub = time.strptime("2026-05-10 10:00:00", "%Y-%m-%d %H:%M:%S")
        entry_data = {
            "link": "https://connpass.com/event/456/",
            "title": "Python 勉強会",
            "summary": "Python エンジニア向けハンズオン",
            "published_parsed": pub,
        }

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            result = du._fetch_connpass_events_rss("20260501")

        # started_at は published_parsed（UTC → JST変換）から設定される
        matching = [e for e in result if e["event_url"] == "https://connpass.com/event/456/"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["started_at"], "2026/05/10 19:00")

    def test_fetch_connpass_filters_past_events(self):
        """fetch_connpass_events() は started_at が実行日より前のイベントを除外する。"""
        import time

        # 実行日 2026-05-20、過去イベント（JST 5/9）と将来イベント（JST 5/24）を用意
        past_pub = time.strptime("2026-05-09 10:00:00", "%Y-%m-%d %H:%M:%S")   # UTC → JST = 5/9 19:00
        future_pub = time.strptime("2026-05-24 10:00:00", "%Y-%m-%d %H:%M:%S")  # UTC → JST = 5/24 19:00

        past_entry_data = {
            "link": "https://connpass.com/event/100/",
            "title": "Python 勉強会（過去）",
            "summary": "Python エンジニア向け",
            "published_parsed": past_pub,
        }
        future_entry_data = {
            "link": "https://connpass.com/event/200/",
            "title": "Python 勉強会（未来）",
            "summary": "Python エンジニア向け",
            "published_parsed": future_pub,
        }

        def make_entry(data):
            e = MagicMock()
            e.get.side_effect = lambda k, d=None: data.get(k, d)
            return e

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(
                entries=[make_entry(past_entry_data), make_entry(future_entry_data)]
            )
            result = du.fetch_connpass_events("20260520")

        urls = [e["event_url"] for e in result]
        self.assertNotIn("https://connpass.com/event/100/", urls, "過去イベントは除外される")
        self.assertIn("https://connpass.com/event/200/", urls, "将来イベントは含まれる")

    def test_fetch_connpass_sorts_events_by_started_at(self):
        """fetch_connpass_events() は started_at の昇順（近い順）でイベントを並べる。"""
        import time

        later_pub = time.strptime("2026-05-28 10:00:00", "%Y-%m-%d %H:%M:%S")   # UTC → JST = 5/28 19:00
        sooner_pub = time.strptime("2026-05-22 10:00:00", "%Y-%m-%d %H:%M:%S")  # UTC → JST = 5/22 19:00

        later_data = {
            "link": "https://connpass.com/event/300/",
            "title": "Python 勉強会（後）",
            "summary": "Python エンジニア向け",
            "published_parsed": later_pub,
        }
        sooner_data = {
            "link": "https://connpass.com/event/400/",
            "title": "Python 勉強会（先）",
            "summary": "Python エンジニア向け",
            "published_parsed": sooner_pub,
        }

        def make_entry(data):
            e = MagicMock()
            e.get.side_effect = lambda k, d=None: data.get(k, d)
            return e

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            # later_data（5/28）を先に返し、sooner_data（5/22）を後に返す
            mock_fp.parse.return_value = MagicMock(
                entries=[make_entry(later_data), make_entry(sooner_data)]
            )
            result = du.fetch_connpass_events("20260520")

        dated = [e for e in result if e.get("started_at")]
        if len(dated) >= 2:
            # started_at の昇順に並んでいることを確認（全隣接ペアを検証）
            for i in range(len(dated) - 1):
                self.assertLessEqual(
                    dated[i]["started_at"], dated[i + 1]["started_at"],
                    f"インデックス {i} と {i+1} の順序が不正: "
                    f"{dated[i]['started_at']} > {dated[i + 1]['started_at']}"
                )

    def test_fetch_connpass_events_no_date_events_after_dated_events(self):
        """fetch_connpass_events() は日時不明イベントを日時有りイベントの後に配置する。"""
        import time

        future_pub = time.strptime("2026-05-25 10:00:00", "%Y-%m-%d %H:%M:%S")  # UTC → JST = 5/25 19:00

        dated_data = {
            "link": "https://connpass.com/event/500/",
            "title": "Python 勉強会（日時あり）",
            "summary": "Python エンジニア向け",
            "published_parsed": future_pub,
        }
        no_date_data = {
            "link": "https://connpass.com/event/600/",
            "title": "Python 勉強会（日時なし）",
            "summary": "Python エンジニア向け",
            "published_parsed": None,
        }

        def make_entry(data):
            e = MagicMock()
            e.get.side_effect = lambda k, d=None: data.get(k, d)
            return e

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            # no_date_data を先に返し、dated_data を後に返す
            mock_fp.parse.return_value = MagicMock(
                entries=[make_entry(no_date_data), make_entry(dated_data)]
            )
            result = du.fetch_connpass_events("20260520")

        # started_at があるイベントが先に来る
        if len(result) >= 2:
            dated_first = [e for e in result if e.get("started_at")]
            no_date_events = [e for e in result if not e.get("started_at")]
            if dated_first and no_date_events:
                first_dated_idx = result.index(dated_first[0])
                first_no_date_idx = result.index(no_date_events[0])
                self.assertLess(first_dated_idx, first_no_date_idx)

    def test_fetch_connpass_v2_does_not_send_undocumented_params(self):
        """CONNPASS_API_KEY が設定された場合、v2 API には未文書パラメータを送信しない。

        connpass v2 API（https://connpass.com/about/api/v2/）の公式パラメータは
        event_id / keyword / keyword_or / ym / ymd / nickname / owner_id /
        series_id / subdomain / start / order / count / format のみ。
        v1 由来の started_at_gte / accepted_end_at_gte は v2 では存在しない。
        """
        captured_params_list: list[dict] = []

        def fake_get(url, params=None, headers=None, timeout=None):
            if headers and "X-API-Key" in headers:
                captured_params_list.append(dict(params or {}))
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"events": [], "results_returned": 0}
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            du.fetch_connpass_events("20260501")

        self.assertTrue(captured_params_list, "v2 API が呼び出されていない")
        allowed_keys = {
            "event_id", "keyword", "keyword_or", "ym", "ymd",
            "nickname", "owner_id", "series_id", "subdomain",
            "start", "order", "count", "format",
        }
        for params in captured_params_list:
            for key in params.keys():
                self.assertIn(
                    key, allowed_keys,
                    f"v2 API に未文書パラメータ {key!r} が送信されている",
                )

    def test_fetch_connpass_v2_handles_event_id_field(self):
        """CONNPASS_API_KEY が設定された場合、v2 レスポンスの event_id フィールドで
        重複排除できる（旧 id フィールドにもフォールバック）。

        event_id を読めていないと seen_ids が空のままとなり重複排除が機能しない。
        URL ベースの seen_urls 重複排除をすり抜けるため、呼び出しごとに **異なる
        URL** を返しつつ **同じ event_id** を返すフェイクを使う。これにより
        event_id 重複排除が実際に効いていなければ複数件採用されてしまうため、
        event_id 経由の dedup のみがテストの成否を決める。
        """
        # 呼び出しごとに URL を変化させて seen_urls dedup を意図的にすり抜ける
        call_counter = {"n": 0}

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            if headers and "X-API-Key" in headers:
                call_counter["n"] += 1
                # 同じ event_id だが URL は呼び出し毎にユニーク
                event = {
                    "event_id": 99999,
                    "title": "クラウドネイティブ勉強会",
                    "catch": "Kubernetes と Azure のハンズオン",
                    "url": (
                        f"https://connpass.com/event/99999/"
                        f"?call={call_counter['n']}"
                    ),
                    "started_at": "2026-05-15T19:00:00+09:00",
                    "place": "東京",
                    "address": "東京都渋谷区",
                    "accepted": 10,
                    "limit": 30,
                    "series": {"title": "TestSeries"},
                }
                resp.json.return_value = {
                    "events": [event],
                    "results_returned": 1,
                }
            else:
                resp.json.return_value = {"events": [], "results_returned": 0}
            return resp

        with (
            patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            result = du.fetch_connpass_events("20260501")

        # 段階5 が複数都道府県・複数月にわたって呼ばれていることを前提条件として確認
        # （でなければそもそも重複排除のテストにならない）
        self.assertGreater(
            call_counter["n"], 1,
            "段階5 の v2 API 呼び出しが複数回発生していない（テスト前提が崩れている）",
        )

        # 同じ event_id のイベントは複数月・複数都道府県呼び出しでも 1 件だけ採用される。
        # URL は呼び出し毎にユニークなので、event_id 重複排除が機能していないと
        # 複数件採用されてしまう。
        matching = [e for e in result if e.get("title") == "クラウドネイティブ勉強会"]
        self.assertEqual(
            len(matching), 1,
            f"event_id による重複排除が機能していない (採用件数={len(matching)})",
        )
        self.assertEqual(matching[0]["started_at"], "2026/05/15 19:00")

    def test_fetch_connpass_v2_paginates_when_results_available_exceeds_count(self):
        """results_available > count の月では start パラメータでページングし、
        後続ページのイベントも取得する。"""
        # ym=202605 のときだけ 2 ページ分のレスポンスを返すフェイク。
        # ページ1: results_returned=100, results_available=150 (start=1)
        # ページ2: results_returned=50, results_available=150 (start=101)
        captured: list[dict] = []

        def make_event(eid: int, day: int = 20) -> dict:
            return {
                "event_id": eid,
                "title": f"Tokyo Cloud Meetup {eid}",
                "catch": "Kubernetes ハンズオン",
                "url": f"https://connpass.com/event/{eid}/",
                "started_at": f"2026-05-{day:02d}T19:00:00+09:00",
                "place": "東京",
                "address": "東京都渋谷区",
                "accepted": 10,
                "limit": 50,
                "series": {"title": "Series"},
            }

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            if not (headers and "X-API-Key" in headers):
                resp.json.return_value = {"events": [], "results_returned": 0}
                return resp
            captured.append(dict(params or {}))
            ym = params.get("ym")
            start = int(params.get("start", 1))
            if ym == "202605":
                if start == 1:
                    # ページ1 のイベントは月の後半 (5/25) → ソート後にカットされやすい
                    events = [make_event(1000 + i, day=25) for i in range(100)]
                    resp.json.return_value = {
                        "events": events,
                        "results_returned": 100,
                        "results_available": 150,
                        "results_start": 1,
                    }
                elif start == 101:
                    # ページ2 のイベントは月の前半 (5/05) → ソートで先頭に来るので
                    # CONNPASS_MAX_EVENTS のカット後も生き残る。これにより
                    # ページングが効いていなければ結果に現れない、を担保できる。
                    events = [make_event(2000 + i, day=5) for i in range(50)]
                    resp.json.return_value = {
                        "events": events,
                        "results_returned": 50,
                        "results_available": 150,
                        "results_start": 101,
                    }
                else:
                    resp.json.return_value = {
                        "events": [],
                        "results_returned": 0,
                        "results_available": 150,
                    }
            else:
                resp.json.return_value = {
                    "events": [],
                    "results_returned": 0,
                    "results_available": 0,
                }
            return resp

        with (
            patch.dict("os.environ", {"CONNPASS_API_KEY": "test-key"}),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[])
            result = du.fetch_connpass_events("20260501")

        # 202605 については start=1 と start=101 の 2 リクエストが発生していること
        ym_starts = [
            (p.get("ym"), int(p.get("start", 1)))
            for p in captured if p.get("ym") == "202605"
        ]
        # 2 都道府県 × 2 ページ = 4 リクエスト（少なくとも start=1 と start=101 の両方）
        starts_for_ym = {start for _, start in ym_starts}
        self.assertIn(1, starts_for_ym, "start=1 のリクエストが発生していない")
        self.assertIn(101, starts_for_ym,
                      "start=101 のページングリクエストが発生していない")

        # ページング結果として後続ページのイベント（event_id 2000+）も取得結果に含まれる
        result_titles = {e["title"] for e in result}
        self.assertTrue(
            any(t.startswith("Tokyo Cloud Meetup 20") for t in result_titles),
            f"ページ2 のイベントが結果に含まれていない: titles={sorted(result_titles)[:5]}",
        )

    def _make_rss_entry(self, event_id: int, published_at: str = "2026-05-25 10:00:00") -> "MagicMock":
        """テスト用の RSS エントリ MagicMock を作成する。"""
        import time as time_mod
        data = {
            "link": f"https://connpass.com/event/{event_id}/",
            "title": f"Python 勉強会 {event_id}",
            "summary": "Python エンジニア向けイベント",
            "published_parsed": time_mod.strptime(published_at, "%Y-%m-%d %H:%M:%S"),
        }
        entry = MagicMock()
        entry.get.side_effect = lambda k, d=None: data.get(k, d)
        return entry

    def test_prev_event_urls_deprioritizes_before_cap_many_new(self):
        """新規イベントが CONNPASS_MAX_EVENTS 以上ある場合、前日重複は後方に回されて結果から除外される。"""
        max_ev = du.CONNPASS_MAX_EVENTS

        # 前日重複 2 件をあえて先頭側・早い日時に置く。
        # 後方移動ロジックが無ければ、単純な [:max_ev] の切り詰めでは重複が結果に残ってしまう。
        duplicate_entries = [
            self._make_rss_entry(max_ev + 1, "2026-05-24 08:00:00"),
            self._make_rss_entry(max_ev + 2, "2026-05-24 09:00:00"),
        ]
        new_entries = [
            self._make_rss_entry(i, f"2026-05-25 {10 + (i % 10):02d}:00:00")
            for i in range(1, max_ev + 1)
        ]
        # 重複を先頭に置くことで、並べ替えロジックがなければ [:max_ev] で重複が残る
        entries = duplicate_entries + new_entries
        prev_event_urls = {
            f"https://connpass.com/event/{max_ev + 1}/",
            f"https://connpass.com/event/{max_ev + 2}/",
        }

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=entries)
            result = du.fetch_connpass_events("20260520", prev_event_urls)

        # 結果は最大 max_ev 件以内
        self.assertLessEqual(len(result), max_ev)
        # 前日重複 URL は結果に含まれない（新規が十分あるため後方に回って除外される）
        result_urls = {e["event_url"] for e in result}
        for url in prev_event_urls:
            self.assertNotIn(url, result_urls, f"前日重複 {url} が除外されていない")

    def test_prev_event_urls_keeps_repeated_when_few_new(self):
        """新規イベントが CONNPASS_MAX_EVENTS 未満の場合、前日重複もリストに含まれる。"""
        max_ev = du.CONNPASS_MAX_EVENTS

        # 前日重複イベントを先頭（早い日時）に置く。並べ替えロジックで末尾に回るが件数が少ないので残る。
        entries = [
            self._make_rss_entry(3, "2026-05-24 08:00:00"),  # 前日重複：最も早い日時で先頭に来る
            self._make_rss_entry(1, "2026-05-25 10:00:00"),
            self._make_rss_entry(2, "2026-05-25 11:00:00"),
        ]
        prev_event_urls = {"https://connpass.com/event/3/"}

        def fake_get(url, params=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=entries)
            result = du.fetch_connpass_events("20260520", prev_event_urls)

        result_urls = {e["event_url"] for e in result}
        # 前日重複イベントもリストに残る（新規が max_ev に満たないため）
        self.assertIn("https://connpass.com/event/3/", result_urls,
                      "新規イベントが少ない場合は前日重複もリストに残るべき")
        # 新規イベントが前日重複より前に来る
        new_indices = [i for i, e in enumerate(result)
                       if e["event_url"] not in prev_event_urls]
        dup_indices = [i for i, e in enumerate(result)
                       if e["event_url"] in prev_event_urls]
        if new_indices and dup_indices:
            self.assertLess(max(new_indices), min(dup_indices),
                            "新規イベントは前日重複より前に並ぶべき")


class TestFetchOtherPlatformEvents(unittest.TestCase):
    """_fetch_other_platform_events() のテスト"""

    def _make_dt(self, date_str: str) -> "datetime":
        import generate_daily_update as d
        return d.datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=d.JST)

    def test_it_event_from_feed_is_included(self):
        """IT 関連エントリはリストに含まれる。"""
        import time
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        # published_parsed: 2026-06-01 00:00:00 UTC
        pub = time.strptime("2026-06-01", "%Y-%m-%d")
        entry = MagicMock()
        entry_data = {
            "link": "https://doorkeeper.jp/events/1",
            "title": "Python 勉強会 東京",
            "summary": "Python エンジニア向けハンズオン",
            "published_parsed": pub,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            seen: set[str] = set()
            result = du._fetch_other_platform_events(seen)

        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0]["event_url"], "https://doorkeeper.jp/events/1")
        self.assertIn("https://doorkeeper.jp/events/1", seen)

    def test_event_included_regardless_of_publication_date(self):
        """published_parsed は期間フィルタに使わないため、公開日が古くても IT イベントは含まれる。"""
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        # published_parsed irrelevant since date filter was removed
        entry = MagicMock()
        entry_data = {
            "link": "https://doorkeeper.jp/events/2",
            "title": "Python 勉強会",
            "summary": "Python エンジニア向け",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            seen: set[str] = set()
            result = du._fetch_other_platform_events(seen)

        # publication date is not used for filtering; IT event should be included
        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0]["started_at"], "")

    def test_non_it_event_is_excluded(self):
        """IT 非関連エントリは除外される。"""
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        entry_data = {
            "link": "https://doorkeeper.jp/events/3",
            "title": "料理教室 東京",
            "summary": "家庭料理を楽しく学びましょう",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            seen: set[str] = set()
            result = du._fetch_other_platform_events(seen)

        self.assertEqual(result, [])

    def test_duplicate_url_is_excluded(self):
        """seen_urls に登録済みの URL は除外される。"""
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        existing_url = "https://doorkeeper.jp/events/4"
        entry_data = {
            "link": existing_url,
            "title": "Python 勉強会",
            "summary": "Python エンジニア向け",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            seen: set[str] = {existing_url}
            result = du._fetch_other_platform_events(seen)

        self.assertEqual(result, [])

    def test_location_filter_excludes_non_tokyo_events(self):
        """location_filter=True のフィードでは東京/神奈川/オンライン無関係のエントリを除外する。"""
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        techplay_url = "https://techplay.jp/atom/events"

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        entry_data = {
            "link": "https://techplay.jp/event/9999",
            "title": "大阪 Python 勉強会",
            "summary": "大阪のエンジニア向けイベント",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            # Temporarily override feeds with only TECH PLAY (location_filter=True)
            original_feeds = du._IT_EVENT_PLATFORM_FEEDS
            du._IT_EVENT_PLATFORM_FEEDS = [{"name": "TECH PLAY", "url": techplay_url, "location_filter": True}]
            try:
                seen: set[str] = set()
                result = du._fetch_other_platform_events(seen)
            finally:
                du._IT_EVENT_PLATFORM_FEEDS = original_feeds

        self.assertEqual(result, [])

    def test_location_filter_includes_online_events(self):
        """location_filter=True のフィードでもオンライン関連エントリは通過する。"""
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        techplay_url = "https://techplay.jp/atom/events"

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        entry_data = {
            "link": "https://techplay.jp/event/8888",
            "title": "オンライン Python ハンズオン",
            "summary": "オンラインで Python エンジニア向け勉強会",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            original_feeds = du._IT_EVENT_PLATFORM_FEEDS
            du._IT_EVENT_PLATFORM_FEEDS = [{"name": "TECH PLAY", "url": techplay_url, "location_filter": True}]
            try:
                seen: set[str] = set()
                result = du._fetch_other_platform_events(seen)
            finally:
                du._IT_EVENT_PLATFORM_FEEDS = original_feeds

        self.assertTrue(len(result) > 0)

    def test_feed_fetch_failure_is_skipped(self):
        """フィード取得失敗時は例外を発生させずに空リストを返す。"""
        import requests as req_mod
        target_dt = self._make_dt("20260501")
        end_dt = self._make_dt("20260731")

        with patch("requests.get", side_effect=req_mod.RequestException("timeout")):
            seen: set[str] = set()
            result = du._fetch_other_platform_events(seen)

        self.assertEqual(result, [])

    def test_platform_feeds_constant_is_nonempty(self):
        """_IT_EVENT_PLATFORM_FEEDS には少なくとも 1 件のフィードが定義されている。"""
        self.assertGreater(len(du._IT_EVENT_PLATFORM_FEEDS), 0)
        for feed in du._IT_EVENT_PLATFORM_FEEDS:
            self.assertIn("name", feed)
            self.assertIn("url", feed)

    def test_techplay_feed_has_location_filter(self):
        """TECH PLAY フィードには location_filter=True が設定されている。"""
        techplay_feeds = [f for f in du._IT_EVENT_PLATFORM_FEEDS if "TECH PLAY" in f.get("name", "")]
        self.assertTrue(len(techplay_feeds) > 0, "TECH PLAY フィードが定義されていない")
        for f in techplay_feeds:
            self.assertTrue(f.get("location_filter"), "TECH PLAY フィードに location_filter=True が必要")

    def test_findy_feed_is_defined(self):
        """Findy フィードが _IT_EVENT_PLATFORM_FEEDS に定義されている。"""
        findy_feeds = [f for f in du._IT_EVENT_PLATFORM_FEEDS if "Findy" in f.get("name", "")]
        self.assertTrue(len(findy_feeds) > 0, "Findy フィードが定義されていない")
        for f in findy_feeds:
            self.assertIn("url", f)
            self.assertIn("findy", f["url"])

    def test_findy_feed_has_started_at_from_published(self):
        """Findy フィードには started_at_from_published=True が設定されている。"""
        findy_feeds = [f for f in du._IT_EVENT_PLATFORM_FEEDS if "Findy" in f.get("name", "")]
        self.assertTrue(len(findy_feeds) > 0, "Findy フィードが定義されていない")
        for f in findy_feeds:
            self.assertTrue(f.get("started_at_from_published"), "Findy フィードに started_at_from_published=True が必要")

    def test_started_at_from_published_sets_started_at(self):
        """started_at_from_published=True のフィードでは published_parsed が started_at に設定される。"""
        import time

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        pub = time.strptime("2026-06-15 10:00:00", "%Y-%m-%d %H:%M:%S")
        entry = MagicMock()
        entry_data = {
            "link": "https://findy.connpass.com/event/100",
            "title": "Python エンジニア勉強会",
            "summary": "Python エンジニア向けハンズオン",
            "published_parsed": pub,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            original_feeds = du._IT_EVENT_PLATFORM_FEEDS
            du._IT_EVENT_PLATFORM_FEEDS = [
                {"name": "Findy", "url": "https://findy.connpass.com/rss", "started_at_from_published": True}
            ]
            try:
                seen: set[str] = set()
                result = du._fetch_other_platform_events(seen)
            finally:
                du._IT_EVENT_PLATFORM_FEEDS = original_feeds

        self.assertTrue(len(result) > 0)
        started_at = result[0]["started_at"]
        self.assertNotEqual(started_at, "")
        # published_parsed は UTC 2026-06-15 10:00 → JST 2026-06-15 19:00
        self.assertEqual(started_at, "2026/06/15 19:00")

    def test_codezine_connpass_feed_is_in_event_platform_feeds(self):
        """Codezine の connpass グループ RSS が _IT_EVENT_PLATFORM_FEEDS に定義されている。

        Codezine は Developers Summit / CodeZine Night 等のイベントを connpass で参加募集するため、
        connpass グループ RSS（codezine.connpass.com/rss）を使用する。
        汎用ニュース RSS（codezine.jp/rss/）は技術記事と混在するため使用しない。
        """
        codezine_feeds = [f for f in du._IT_EVENT_PLATFORM_FEEDS if "Codezine" in f.get("name", "")]
        self.assertTrue(len(codezine_feeds) > 0, "Codezine フィードが _IT_EVENT_PLATFORM_FEEDS に定義されていない")
        for f in codezine_feeds:
            self.assertIn("url", f)
            self.assertIn("codezine.connpass.com", f["url"], "Codezine は connpass グループ RSS を使用すること（汎用ニュース RSS は不可）")
            self.assertTrue(f.get("started_at_from_published"), "Codezine connpass フィードには started_at_from_published=True が必要")

    def test_event_filter_excludes_non_event_entries(self):
        """event_filter=True のフィードでは、イベント告知語のないエントリを除外する。"""

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        entry_data = {
            "link": "https://codezine.jp/article/1234",
            "title": "Python 最新機能解説 東京",
            "summary": "Python 3.13 の新機能について解説",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            original_feeds = du._IT_EVENT_PLATFORM_FEEDS
            du._IT_EVENT_PLATFORM_FEEDS = [
                {"name": "Codezine", "url": "https://codezine.jp/rss/new/20/index.xml",
                 "location_filter": True, "event_filter": True}
            ]
            try:
                seen: set[str] = set()
                result = du._fetch_other_platform_events(seen)
            finally:
                du._IT_EVENT_PLATFORM_FEEDS = original_feeds

        self.assertEqual(result, [])

    def test_event_filter_includes_event_entries(self):
        """event_filter=True のフィードでも、イベント告知語を含むエントリは通過する。"""

        def fake_get(url, headers=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.content = b""
            return resp

        entry = MagicMock()
        entry_data = {
            "link": "https://codezine.jp/article/5678",
            "title": "Python セミナー 東京 開催",
            "summary": "Python エンジニア向けセミナーを東京で開催します",
            "published_parsed": None,
            "updated_parsed": None,
        }
        entry.get.side_effect = lambda k, d=None: entry_data.get(k, d)

        with (
            patch("requests.get", side_effect=fake_get),
            patch.object(du, "feedparser") as mock_fp,
        ):
            mock_fp.parse.return_value = MagicMock(entries=[entry])
            original_feeds = du._IT_EVENT_PLATFORM_FEEDS
            du._IT_EVENT_PLATFORM_FEEDS = [
                {"name": "Codezine", "url": "https://codezine.jp/rss/new/20/index.xml",
                 "location_filter": True, "event_filter": True}
            ]
            try:
                seen: set[str] = set()
                result = du._fetch_other_platform_events(seen)
            finally:
                du._IT_EVENT_PLATFORM_FEEDS = original_feeds

        self.assertTrue(len(result) > 0)

    def test_event_filter_keywords_constant_is_nonempty(self):
        """_EVENT_FILTER_KEYWORDS が定義されており空でない。"""
        self.assertTrue(len(du._EVENT_FILTER_KEYWORDS) > 0)
        self.assertIn("イベント", du._EVENT_FILTER_KEYWORDS)
        self.assertIn("セミナー", du._EVENT_FILTER_KEYWORDS)
        self.assertIn("勉強会", du._EVENT_FILTER_KEYWORDS)

    def test_location_filter_keywords_constant_is_nonempty(self):
        """_LOCATION_FILTER_KEYWORDS が定義されており空でない。"""
        self.assertTrue(len(du._LOCATION_FILTER_KEYWORDS) > 0)
        self.assertIn("東京", du._LOCATION_FILTER_KEYWORDS)
        self.assertIn("オンライン", du._LOCATION_FILTER_KEYWORDS)


class TestDailyUpdateSinceWindow(unittest.TestCase):
    """デイリー更新の収集開始時刻計算のテスト"""

    def test_compute_since_is_previous_day_0730_jst(self):
        """compute_since() は対象日の前日 07:30 JST を返す。"""
        since = du.compute_since("20260415")
        self.assertEqual(since.isoformat(), "2026-04-14T07:30:00+09:00")


class TestFetchFeedDateFilterDailyUpdate(unittest.TestCase):
    """_fetch_feed() の日付フィルタリングのテスト

    通常窓（since、直近 1〜2 日）では `since` 以降のみを通し、日付なしを除外する。
    `_regenerate_empty_sections` 経由で since が拡張窓（直近 1 か月）に
    設定された場合は、その範囲内の古い記事も取得できる（絶対上限 cap を持たない）。
    """

    def _make_feed(self, entries: list[dict]):
        """feedparser.FeedParserDict 相当のモックを返す。"""
        mock_feed = MagicMock()
        mock_entries = []
        for e in entries:
            entry = MagicMock()
            entry.get.side_effect = lambda key, default="", _e=e: _e.get(key, default)
            entry.published_parsed = e.get("published_parsed")
            entry.updated_parsed = e.get("updated_parsed")
            entry.link = e.get("link", "https://example.com/article")
            mock_entries.append(entry)
        mock_feed.entries = mock_entries
        return mock_feed

    def _run(self, entries: list[dict], since):
        """requests と feedparser をモックして _fetch_feed を呼ぶ。"""
        mock_resp = MagicMock()
        mock_resp.content = b""
        mock_feed = self._make_feed(entries)
        with (patch.object(du.requests, "get", return_value=mock_resp),
              patch.object(du.feedparser, "parse", return_value=mock_feed),
              patch.object(ags, "_resolve_google_news_url", side_effect=lambda u: u)):
            return du._fetch_feed("https://feed.example.com/rss", since)

    def _time_tuple(self, dt):
        return dt.timetuple()[:6]

    def test_article_older_than_since_is_excluded(self):
        """`since` より古い日付を持つ記事は除外される（前回実行以前の情報）。"""
        from datetime import datetime, timedelta, timezone
        # 相対時刻で組み立てて、テスト実行日に依存しないようにする
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        old = since - timedelta(hours=1)
        entries = [{
            "title": "Old Article",
            "link": "https://example.com/old",
            "published_parsed": self._time_tuple(old),
            "updated_parsed": None,
        }]
        self.assertEqual(len(self._run(entries, since)), 0)

    def test_article_without_date_is_excluded(self):
        """日付のない記事は新鮮さを確認できないため除外される（古い情報の混入防止）。"""
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(hours=12)
        entries = [{
            "title": "No Date Article",
            "link": "https://example.com/nodate",
            "published_parsed": None,
            "updated_parsed": None,
        }]
        self.assertEqual(len(self._run(entries, since)), 0,
                         "日付のない記事は除外されるべき")

    def test_recent_article_within_since_window_is_included(self):
        """since 以降の記事は含まれる。"""
        from datetime import datetime, timedelta, timezone
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        fresh = datetime.now(timezone.utc) - timedelta(minutes=30)
        entries = [{
            "title": "Fresh Article",
            "link": "https://example.com/fresh",
            "published_parsed": self._time_tuple(fresh),
            "updated_parsed": None,
        }]
        result = self._run(entries, since)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Fresh Article")

    def test_old_article_included_when_since_is_distant_past(self):
        """since が遠い過去（拡張窓フォールバック相当）の場合、
        その範囲内の古い記事は除外されない（絶対上限の cap を持たない）。"""
        from datetime import datetime, timedelta, timezone
        # _regenerate_empty_sections の拡張窓（EXTENDED_LOOKBACK_DAYS=30 日）を想定
        since = datetime.now(timezone.utc) - timedelta(days=du.EXTENDED_LOOKBACK_DAYS)
        # 拡張窓内の 10 日前の記事は含まれるべき
        old_but_in_window = datetime.now(timezone.utc) - timedelta(days=10)
        entries = [{
            "title": "Old But In Extended Window",
            "link": "https://example.com/extended",
            "published_parsed": self._time_tuple(old_but_in_window),
            "updated_parsed": None,
        }]
        result = self._run(entries, since)
        self.assertEqual(len(result), 1,
                         "拡張窓内の古い記事はフォールバック時に取得できるべき")

    def test_extended_lookback_days_constant_is_30(self):
        """EXTENDED_LOOKBACK_DAYS は 30 日（直近 1 か月）に設定されている。"""
        self.assertEqual(du.EXTENDED_LOOKBACK_DAYS, 30)

    def test_azure_update_url_converted_to_ja_jp(self):
        """generate_daily_update._fetch_feed は Azure アップデート URL を ja-jp 形式に変換する。

        Azure Release Communications RSS フィードが提供する URL はロケールなし
        （/updates?id=NNNN）だが、_fetch_feed 経由で取得した記事の url は
        /ja-jp/updates?id=NNNN 形式に変換されることを確認する。
        """
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        fresh = datetime.now(timezone.utc) - timedelta(minutes=30)
        entries = [{
            "title": "Azure Backup GA",
            "link": "https://azure.microsoft.com/updates?id=560904",
            "summary": "Azure Backup now supports...",
            "published_parsed": self._time_tuple(fresh),
            "updated_parsed": None,
        }]
        result = self._run(entries, since)
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["url"],
            "https://azure.microsoft.com/ja-jp/updates?id=560904",
        )


class TestValidateLinksOrphanedSeparatorsDailyUpdate(unittest.TestCase):
    """validate_links() の孤立した --- セパレータ除去テスト"""

    def _make_article_with_invalid_link(self, url: str = "https://bad.example.com") -> str:
        return (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n内容A\n\n**リンク**: [タイトルA](https://good.example.com)\n\n"
            "---\n\n"
            f"### トピックB\n\n内容B\n\n**リンク**: [タイトルB]({url})\n\n"
            "---\n\n"
            "## 2. ニュースで話題のテーマ\n\n"
        )

    def test_orphan_separators_removed_when_topic_deleted(self):
        """リンク無効でトピック除去後に残った孤立 --- が除去される。"""
        article = self._make_article_with_invalid_link()
        with (
            patch.object(ags, "_validate_url", return_value=(False, "HTTP 404")),
            patch.object(ags, "_search_alternative_url", return_value=None),
        ):
            result = du.validate_links(article)
        self.assertNotIn("\n---\n\n---\n", result)
        self.assertNotIn("\n---\n\n## ", result)

    def test_valid_separators_preserved(self):
        """有効なリンクのみを含む記事では --- セパレータが保持される。"""
        article = self._make_article_with_invalid_link()
        with patch.object(ags, "_validate_url", return_value=(True, "OK")):
            result = du.validate_links(article)
        self.assertIn("---", result)


class TestRegenerateEmptySectionsDailyUpdate(unittest.TestCase):
    """_regenerate_empty_sections() のテスト"""

    _SECTION_DEF = next(s for s in du.SECTION_DEFINITIONS if s["key"] == "azure")
    _HEADER = _SECTION_DEF["header"]

    def _make_llm_clients(self, content: str = "## 1. Azure アップデート情報\n\n### 新トピック\n内容"):
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        client.chat.completions.create.return_value.choices = [choice]
        return [(client, "gpt-4o")]

    def test_section_with_topics_is_not_regenerated(self):
        """トピックが存在するセクションは再生成されない。"""
        article = f"{self._HEADER}\n\n### 既存トピック\n内容\n\n"
        with patch.object(du, "fetch_general_news", return_value=[]):
            result = du._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"azure": []},
                MagicMock(),
                self._make_llm_clients(),
            )
        self.assertIn("既存トピック", result)

    def test_empty_section_is_regenerated(self):
        """空セクション（トピックなし）は再生成される。"""
        article = f"{self._HEADER}\n\n"
        new_items = [{"url": "https://new.example.com", "title": "新Azure記事"}]
        llm_clients = self._make_llm_clients()

        with (
            patch.object(du, "_fetch_section_category", return_value=new_items),
            patch.object(du, "validate_links", side_effect=lambda x: x),
        ):
            result = du._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"azure": []},
                MagicMock(),
                llm_clients,
            )
        self.assertIn("新トピック", result)

    def test_no_new_items_writes_no_info_message(self):
        """専用フィードも汎用フィードも新規データなければ情報なしメッセージが記載される。"""
        article = f"{self._HEADER}\n\n"

        with (
            patch.object(du, "_fetch_section_category", return_value=[]),
            patch.object(du, "fetch_general_news", return_value=[]),
        ):
            result = du._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"azure": []},
                MagicMock(),
                self._make_llm_clients(),
            )
        self.assertIn("現在の対象期間に該当する情報はありません。", result)

    def test_community_section_is_skipped(self):
        """dict 型データの community セクションは再生成対象外。"""
        community_def = next(s for s in du.SECTION_DEFINITIONS if s["key"] == "community")
        header = community_def["header"]
        article = f"{header}\n\n"  # no ### topics

        llm_clients = self._make_llm_clients("コミュニティ出力")
        with patch.object(du, "_fetch_section_category", return_value=[]) as mock_fetch:
            du._regenerate_empty_sections(
                article,
                [community_def],
                {"community": {"key": "value"}},
                MagicMock(),
                llm_clients,
            )
        mock_fetch.assert_not_called()

    def test_no_category_items_falls_back_to_general_news(self):
        """専用フィードに新規データがなければ汎用ニュースにフォールバックして LLM を呼ぶ。"""
        tech_def = next(s for s in du.SECTION_DEFINITIONS if s["key"] == "tech")
        header = tech_def["header"]
        article = f"{header}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]
        general_items = [{"url": "https://general.example.com", "title": "汎用ニュース"}]
        new_content = f"{header}\n\n### 汎用トピック\n内容"
        llm_clients = self._make_llm_clients(new_content)
        client = llm_clients[0][0]

        with (
            patch.object(du, "_fetch_section_category", return_value=original_items),
            patch.object(du, "fetch_general_news", return_value=general_items),
            patch.object(du, "validate_links", side_effect=lambda x: x),
        ):
            result = du._regenerate_empty_sections(
                article,
                [tech_def],
                {"tech": original_items},
                MagicMock(),
                llm_clients,
            )

        client.chat.completions.create.assert_called_once()
        self.assertIn("汎用トピック", result)

    def test_general_news_fallback_excludes_original_urls(self):
        """汎用ニュースフォールバック時も元データの URL が除外される。"""
        tech_def = next(s for s in du.SECTION_DEFINITIONS if s["key"] == "tech")
        header = tech_def["header"]
        article = f"{header}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]
        captured_exclude = {}

        def fake_fetch_general_news(since, exclude_urls=None):
            captured_exclude["urls"] = set(exclude_urls or set())
            return []

        with (
            patch.object(du, "_fetch_section_category", return_value=original_items),
            patch.object(du, "fetch_general_news", side_effect=fake_fetch_general_news),
        ):
            du._regenerate_empty_sections(
                article,
                [tech_def],
                {"tech": original_items},
                MagicMock(),
                self._make_llm_clients(),
            )

        self.assertIn("https://old.example.com", captured_exclude.get("urls", set()))

    def test_official_only_section_skips_general_news_fallback(self):
        """official_only=True のセクション（Azure 等）は汎用ニュースへのフォールバックを行わない。"""
        article = f"{self._HEADER}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]

        with (
            patch.object(du, "_fetch_section_category", return_value=original_items),
            patch.object(du, "fetch_general_news") as mock_general,
        ):
            result = du._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"azure": original_items},
                MagicMock(),
                self._make_llm_clients(),
            )

        mock_general.assert_not_called()
        self.assertIn("現在の対象期間に該当する情報はありません。", result)

    def test_no_info_message_section_is_not_reprocessed(self):
        """「情報なし」メッセージが既に記載されているセクションは再処理されない。"""
        article = f"{self._HEADER}\n\n現在の対象期間に該当する情報はありません。"

        with patch.object(du, "_fetch_section_category", return_value=[]) as mock_fetch:
            du._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"azure": []},
                MagicMock(),
                self._make_llm_clients(),
            )
        mock_fetch.assert_not_called()


class TestFormatBareReferenceLinksDailyUpdate(unittest.TestCase):
    """_format_bare_reference_links() のテスト"""

    def test_bare_url_converted_using_heading(self):
        """裸の URL が直近の ### 見出しをラベルにしたハイパーリンクへ変換される。"""
        md = (
            "### Azure Monitor の新機能\n\n"
            "**要約**: 内容\n\n"
            "**リンク**: https://docs.microsoft.com/azure/monitor/\n"
        )
        result = du._format_bare_reference_links(md)
        self.assertIn("[Azure Monitor の新機能](https://docs.microsoft.com/azure/monitor/)", result)
        self.assertNotIn("**リンク**: https://", result)

    def test_url_as_label_converted_using_heading(self):
        """[https://...](https://...) 形式が見出しをラベルにしたリンクへ変換される。"""
        md = (
            "### AWS CLI の変更\n\n"
            "**リンク**: [https://aws.amazon.com/blogs/news/](https://aws.amazon.com/blogs/news/)\n"
        )
        result = du._format_bare_reference_links(md)
        self.assertIn("[AWS CLI の変更](https://aws.amazon.com/blogs/news/)", result)
        self.assertNotIn("[https://", result)

    def test_already_formatted_link_unchanged(self):
        """既に [タイトル](URL) 形式のリンクは変更されない。"""
        md = (
            "### トピック\n\n"
            "**リンク**: [詳細記事](https://example.com/article)\n"
        )
        result = du._format_bare_reference_links(md)
        self.assertIn("[詳細記事](https://example.com/article)", result)

    def test_no_heading_falls_back_to_url_as_label(self):
        """直前に ### 見出しがない場合、URL 自身がラベルに使われる。"""
        md = "**リンク**: https://example.com/fallback\n"
        result = du._format_bare_reference_links(md)
        self.assertIn("[https://example.com/fallback](https://example.com/fallback)", result)


class TestIsItEvent(unittest.TestCase):
    """_is_it_event() のテスト"""

    def _ev(self, title: str, catch: str = "") -> dict:
        return {"title": title, "catch": catch}

    # --- IT 関連イベント（True を返すべきもの） ---

    def test_azure_in_title(self):
        """Azure キーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("Azure User Group 東京 勉強会")))

    def test_aws_jaws_in_title(self):
        """AWS/JAWS キーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("JAWS-UG 東京 AWS re:Invent 報告会")))

    def test_kubernetes_in_title(self):
        """Kubernetes キーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("Kubernetes ハンズオン入門")))

    def test_aiops_in_title(self):
        """AIOps キーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("AIOps コミュニティ meetup")))

    def test_finops_in_title(self):
        """FinOps キーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("FinOps コミュニティ 勉強会")))

    def test_llm_in_catch(self):
        """LLM キーワードがキャッチコピーに含まれる場合も True。"""
        self.assertTrue(du._is_it_event(self._ev("AIイベント", "LLM を使った RAG 実装入門")))

    def test_ai_word_boundary_match(self):
        """'ai' は単語境界マッチで IT イベントを正しく検出する。"""
        self.assertTrue(du._is_it_event(self._ev("生成AI 活用事例")))
        self.assertTrue(du._is_it_event(self._ev("Azure AI Studio ハンズオン")))

    def test_ml_word_boundary_match(self):
        """'ml' は単語境界マッチで ML イベントを正しく検出する。"""
        self.assertTrue(du._is_it_event(self._ev("ML エンジニアのための勉強会")))

    def test_go_word_boundary_match(self):
        """'go' は単語境界マッチで Go 言語イベントを正しく検出する。"""
        self.assertTrue(du._is_it_event(self._ev("Go 言語入門ハンズオン")))

    def test_python_in_title(self):
        """Python キーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("Python 初心者向けプログラミング")))

    def test_security_in_title(self):
        """セキュリティキーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("クラウドセキュリティ 脆弱性対策入門")))

    def test_engineer_in_title(self):
        """エンジニアキーワードを含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("インフラエンジニア向け勉強会")))

    # --- 非 IT イベント（False を返すべきもの） ---

    def test_cooking_event(self):
        """料理教室は False。"""
        self.assertFalse(du._is_it_event(self._ev("料理教室 夏のスイーツ特集")))

    def test_sports_event(self):
        """スポーツイベントは False。"""
        self.assertFalse(du._is_it_event(self._ev("ラグビークラブ 6年生送り出しイベント")))

    def test_childcare_event(self):
        """育児・保育イベントは False。"""
        self.assertFalse(du._is_it_event(self._ev("保育室プレオープンイベント", "子育て支援")))

    def test_driving_event(self):
        """ドライビングレッスンは False。"""
        self.assertFalse(du._is_it_event(self._ev("ドライビングレッスン参加ガイド")))

    def test_immigration_event(self):
        """移住促進イベントは False。"""
        self.assertFalse(du._is_it_event(self._ev("移住促進イベント 日ケ谷地区")))

    def test_game_non_it_event(self):
        """IT 系でないゲームイベントは False。"""
        self.assertFalse(du._is_it_event(self._ev("ポケモンマスターズ ジムバトル大会")))

    def test_psychology_event(self):
        """心理学研究会は False。"""
        self.assertFalse(du._is_it_event(self._ev("心理学研究会 生命過程としての心")))

    def test_bmw_event(self):
        """自動車イベントは False。"""
        self.assertFalse(du._is_it_event(self._ev("BMW X Series 試乗イベント", "自動車")))

    # --- 短いキーワードの誤ヒット防止 ---

    def test_ai_no_false_positive_in_painting(self):
        """'painting' 内の 'ai' で誤ヒットしない。"""
        self.assertFalse(du._is_it_event(self._ev("Painting workshop", "アートと絵画")))

    def test_ml_no_false_positive_in_html(self):
        """'html' 内の 'ml' で誤ヒットしない。"""
        self.assertFalse(du._is_it_event(self._ev("HTML 入門教室", "HTML/CSS でウェブを作ろう")))

    def test_go_no_false_positive_in_ago(self):
        """'ago' 内の 'go' で誤ヒットしない。"""
        self.assertFalse(du._is_it_event(self._ev("2 weeks ago event recap", "料理の振り返り")))

    def test_soc_no_false_positive_in_soccer(self):
        """'soccer' 内の 'soc' で誤ヒットしない。"""
        self.assertFalse(du._is_it_event(self._ev("Soccer team practice", "サッカー")))

    # --- 拡張キーワードのテスト（勉強会・ハンズオン・API） ---

    def test_study_group_in_title(self):
        """「勉強会」を含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("TypeScript 勉強会 Vol.3")))

    def test_hands_on_in_title(self):
        """「ハンズオン」を含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("Docker ハンズオン初心者向け")))

    def test_open_source_ja_in_title(self):
        """「オープンソース」を含むタイトルは True。"""
        self.assertTrue(du._is_it_event(self._ev("オープンソース貢献入門")))

    def test_open_source_en_in_catch(self):
        """'open source' を含むキャッチは True。"""
        self.assertTrue(du._is_it_event(self._ev("OSS イベント", "open source contribution")))

    def test_api_word_boundary_match(self):
        """'api' は単語境界マッチで API イベントを正しく検出する。"""
        self.assertTrue(du._is_it_event(self._ev("REST API 設計入門")))
        self.assertTrue(du._is_it_event(self._ev("API ゲートウェイ勉強会")))

    def test_api_no_false_positive(self):
        """'api' は部分文字列（例: 'capital'）で誤ヒットしない。"""
        self.assertFalse(du._is_it_event(self._ev("Capital city tourism", "旅行")))


class TestVerifyContentDailyUpdate(unittest.TestCase):
    """verify_content() の検証プロセスのテスト"""

    def test_valid_article_unchanged(self):
        """正しい形式の記事は変更されない。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### Azure Functions の新機能\n\n"
            "**要約**: テスト要約\n\n"
            "**影響**: テスト影響\n\n"
            "**リンク**: [Azure Functions](https://example.com/azure)\n"
        )
        result = du.verify_content(md)
        self.assertEqual(result.strip(), md.strip())

    def test_heading_hyperlink_is_unlinked(self):
        """### [タイトル](URL) 形式の見出しからリンクが除去される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### [Azure Update](https://example.com/azure)\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [Azure Update](https://example.com/azure)\n"
        )
        result = du.verify_content(md)
        self.assertIn("### Azure Update", result)
        self.assertNotIn("### [Azure Update](https://", result)

    def test_heading_wrapped_in_brackets_is_unwrapped(self):
        """### [タイトル] 形式（URL なしで全体が角括弧で囲まれた見出し）の角括弧が除去される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### [Generally Available: Premium SSD v2 for Azure Database for PostgreSQL]\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com/azure)\n"
        )
        result = du.verify_content(md)
        self.assertIn(
            "### Generally Available: Premium SSD v2 for Azure Database for PostgreSQL",
            result,
        )
        self.assertNotIn("### [Generally Available", result)

    def test_heading_with_partial_brackets_is_preserved(self):
        """見出しの一部にのみ角括弧がある場合（例: [In preview]）は変更されない。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### [In preview] New Feature\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n"
        )
        result = du.verify_content(md)
        self.assertIn("### [In preview] New Feature", result)

    def test_missing_summary_detected(self):
        """**要約** が欠落しているトピックが検出ログに出力される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "内容のみ\n\n"
            "**リンク**: [タイトル](https://example.com)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = du.verify_content(md)
        self.assertIsInstance(result, str)
        self.assertIn("要約なし:", mock_out.getvalue())

    def test_missing_reference_link_detected(self):
        """**リンク** が欠落しているトピックが検出ログに出力される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = du.verify_content(md)
        self.assertIsInstance(result, str)
        self.assertIn("リンクなし:", mock_out.getvalue())

    def test_malformed_reference_link_detected(self):
        """**リンク** が [text](URL) 形式でないトピックが検出ログに出力される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: https://example.com/bare\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = du.verify_content(md)
        self.assertIsInstance(result, str)
        self.assertIn("リンク形式不正:", mock_out.getvalue())

    def test_closing_sentence_removed(self):
        """セクション末尾の締め文が除去される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**影響**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n\n"
            "以上が本日のアップデート情報です。\n\n"
            "## 2. ニュースで話題のテーマ\n"
        )
        result = du.verify_content(md)
        self.assertNotIn("以上が本日の", result)

    def test_no_info_section_skipped(self):
        """「情報なし」メッセージのセクションは検証をスキップする。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "現在の対象期間に該当する情報はありません。\n"
        )
        result = du.verify_content(md)
        self.assertIn("現在の対象期間に該当する情報はありません。", result)

    def test_orphan_separator_after_section_header_removed(self):
        """## ヘッダー直後の --- セパレータが除去される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "---\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n"
        )
        result = du.verify_content(md)
        # ヘッダー直後の --- が除去されること
        self.assertNotIn("## 1. Azure アップデート情報\n\n---", result)

    def test_community_subsection_headings_skip_summary_check(self):
        """コミュニティセクションの📅/📝サブセクションでは要約チェックをスキップする。"""
        md = (
            "## 5. コミュニティイベント情報（東京・神奈川）\n\n"
            "### 📅 申し込み受付中のイベント\n\n"
            "- イベントA\n- イベントB\n\n"
            "### 📝 参加レポート・イベント宣伝まとめ\n\n"
            "- レポートA\n"
        )
        # 📅/📝 サブセクションで要約・リンクの欠落が検出されないことを確認
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = du.verify_content(md)
        self.assertIsInstance(result, str)
        output = mock_out.getvalue()
        self.assertNotIn("要約なし:", output)
        self.assertNotIn("リンクなし:", output)


class TestSourceUrlTrackerDelegationInDailyUpdate(unittest.TestCase):
    """generate_daily_update.py が SourceUrlTracker に委譲することの確認テスト

    ロジックの詳細テストは test_article_generator_shared.py で一元管理する。
    """

    def test_collect_source_urls_is_tracker_method(self):
        """_collect_source_urls は SourceUrlTracker.collect_source_urls に委譲する。"""
        from article_generator_shared import SourceUrlTracker
        self.assertIs(du._collect_source_urls, SourceUrlTracker.collect_source_urls)

    def test_log_unsourced_is_tracker_method(self):
        """_log_unsourced_reference_links は SourceUrlTracker.log_unsourced_reference_links に委譲する。"""
        from article_generator_shared import SourceUrlTracker
        self.assertIs(du._log_unsourced_reference_links, SourceUrlTracker.log_unsourced_reference_links)

    def test_collect_source_urls_works_via_alias(self):
        """エイリアス経由でも正しく URL を収集できる（統合確認）。"""
        data = [{"url": "https://example.com/a"}, {"event_url": "https://connpass.com/event/1/"}]
        result = du._collect_source_urls(data)
        self.assertIn("https://example.com/a", result)
        self.assertIn("https://connpass.com/event/1/", result)

    def test_log_unsourced_works_via_alias(self):
        """エイリアス経由でも正しくログ出力できる（統合確認）。"""
        article = "### A\n\n**リンク**: [A](https://sourced.example.com)\n"
        source_urls = frozenset({"https://sourced.example.com"})
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            du._log_unsourced_reference_links(article, source_urls)
        self.assertIn("一致", mock_out.getvalue())


class TestBuildEventSummary(unittest.TestCase):
    """_build_event_summary() のテスト"""

    def test_catch_only_returned_when_no_description(self):
        """description がない場合、catch をそのまま返す。"""
        result = du._build_event_summary("短い概要", "")
        self.assertEqual(result, "短い概要")

    def test_none_inputs_returns_empty_string(self):
        """catch も description も None の場合、空文字列を返す（TypeError が起きない）。"""
        result = du._build_event_summary(None, None)
        self.assertEqual(result, "")

    def test_none_catch_fallback_to_empty(self):
        """catch が None、description が空の場合、空文字列を返す。"""
        result = du._build_event_summary(None, "")
        self.assertEqual(result, "")

    def test_empty_inputs_returns_empty_string(self):
        """catch も description も空の場合、空文字列を返す。"""
        result = du._build_event_summary("", "")
        self.assertEqual(result, "")

    def test_description_html_stripped(self):
        """description の HTML タグが除去される。"""
        result = du._build_event_summary("", "<p>テスト内容</p>")
        self.assertIn("テスト内容", result)
        self.assertNotIn("<p>", result)

    def test_description_html_entities_decoded(self):
        """HTML エンティティが変換される。"""
        result = du._build_event_summary("", "<p>A&amp;B &lt;C&gt;</p>")
        self.assertIn("A&B <C>", result)

    def test_exclude_section_html_heading_cut(self):
        """HTML 見出し <h2>注意事項</h2> 以降は切り捨てられる。"""
        desc = "<p>概要テキスト</p><h2>注意事項</h2><p>キャンセル禁止</p>"
        result = du._build_event_summary("", desc)
        self.assertIn("概要テキスト", result)
        self.assertNotIn("キャンセル禁止", result)

    def test_exclude_section_markdown_heading_cut(self):
        """マークダウン見出し ## 注意事項 以降は切り捨てられる（HTML 除去後）。"""
        desc = "概要テキスト\n## 注意事項\nキャンセル禁止"
        result = du._build_event_summary("", desc)
        self.assertIn("概要テキスト", result)
        self.assertNotIn("キャンセル禁止", result)

    def test_exclude_section_markdown_deep_heading_cut(self):
        """マークダウン見出し #### 注意事項（h4）以降も切り捨てられる。"""
        desc = "概要テキスト\n#### 注意事項\nキャンセル禁止"
        result = du._build_event_summary("", desc)
        self.assertIn("概要テキスト", result)
        self.assertNotIn("キャンセル禁止", result)

    def test_description_preferred_over_catch(self):
        """description がある場合、catch は使わず description を返す。"""
        result = du._build_event_summary("キャッチコピー", "<p>詳細説明文</p>")
        self.assertNotIn("キャッチコピー", result)
        self.assertIn("詳細説明文", result)

    def test_exclude_section_nested_html_heading_cut(self):
        """<h2><span>注意事項</span></h2> のようにネストしたタグがあっても切り捨てられる。"""
        desc = "<p>概要テキスト</p><h2><span>注意事項</span></h2><p>キャンセル禁止</p>"
        result = du._build_event_summary("", desc)
        self.assertIn("概要テキスト", result)
        self.assertNotIn("キャンセル禁止", result)

    def test_combined_truncated_at_200_chars(self):
        """結合後のテキストが 200 文字を超える場合、省略記号で切り詰める。"""
        long_desc = "<p>" + "B" * 250 + "</p>"
        result = du._build_event_summary("", long_desc)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 203)  # 200 chars + "..."

    def test_timetable_included_when_before_exclude_section(self):
        """タイムテーブルが注意事項より前にある場合は概要に含まれる。"""
        desc = "<p>概要</p><h2>タイムテーブル</h2><p>19:00 開始</p><h2>注意事項</h2><p>禁止</p>"
        result = du._build_event_summary("", desc)
        self.assertIn("19:00 開始", result)
        self.assertNotIn("禁止", result)


class TestBuildConnpassSectionScripted(unittest.TestCase):
    """_build_connpass_section_scripted() のテスト"""

    def test_empty_events_returns_no_info_message(self):
        """イベントなしの場合、情報なしメッセージを返す。"""
        result = du._build_connpass_section_scripted([])
        self.assertIn("### 📅 申し込み受付中のイベント", result)
        self.assertIn("現在取得できるイベント情報はありません", result)

    def test_section_starts_with_heading(self):
        """出力は ### 📅 申し込み受付中のイベント で始まる。"""
        events = [{"title": "テストイベント", "event_url": "https://connpass.com/event/1/"}]
        result = du._build_connpass_section_scripted(events)
        self.assertTrue(result.startswith("### 📅 申し込み受付中のイベント"))

    def test_event_with_url_creates_hyperlink(self):
        """event_url があるイベントはハイパーリンク形式で出力される。"""
        events = [{"title": "Azure勉強会", "event_url": "https://connpass.com/event/123/"}]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("[Azure勉強会](https://connpass.com/event/123/)", result)

    def test_event_without_url_uses_plain_title(self):
        """event_url がないイベントはプレーンテキストで出力される。"""
        events = [{"title": "URLなしイベント", "event_url": ""}]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**URLなしイベント**", result)
        self.assertNotIn("[URLなしイベント](", result)

    def test_started_at_shown_when_present(self):
        """started_at があれば開催日時が出力される。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "started_at": "2026/05/15 19:00",
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**開催日時**: 2026/05/15 19:00", result)

    def test_started_at_omitted_when_empty(self):
        """started_at が空の場合、開催日時行は出力されない。"""
        events = [{"title": "イベント", "event_url": "https://connpass.com/event/1/", "started_at": ""}]
        result = du._build_connpass_section_scripted(events)
        self.assertNotIn("開催日時:", result)
        self.assertNotIn("**開催日時**:", result)

    def test_place_shown_when_present(self):
        """place があれば場所が出力される。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "place": "東京都渋谷区",
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**場所**: 東京都渋谷区", result)

    def test_address_used_when_place_empty(self):
        """place が空で address がある場合、address が場所として使われる。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "place": "", "address": "東京都新宿区1-1-1",
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**場所**: 東京都新宿区1-1-1", result)

    def test_catch_truncated_at_200_chars(self):
        """catch が 200 文字を超える場合、省略記号で切り詰める。"""
        long_catch = "A" * 250
        events = [{"title": "イベント", "event_url": "https://connpass.com/event/1/", "catch": long_catch}]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**概要**: " + "A" * 200 + "...", result)

    def test_catch_not_truncated_when_short(self):
        """catch が 200 文字以下の場合、省略記号なしでそのまま出力される。"""
        short_catch = "短い概要"
        events = [{"title": "イベント", "event_url": "https://connpass.com/event/1/", "catch": short_catch}]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**概要**: 短い概要", result)
        self.assertNotIn("**概要**: 短い概要...", result)

    def test_description_html_used_as_summary(self):
        """description フィールドがある場合、HTML を除去して概要に使われる。"""
        events = [{
            "title": "イベント",
            "event_url": "https://connpass.com/event/1/",
            "catch": "キャッチ",
            "description": "<p>詳細な説明文</p><h2>注意事項</h2><p>禁止事項</p>",
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**概要**:", result)
        self.assertIn("詳細な説明文", result)
        self.assertNotIn("禁止事項", result)

    def test_summary_shown_when_description_only(self):
        """catch が空でも description があれば概要が出力される。"""
        events = [{
            "title": "イベント",
            "event_url": "https://connpass.com/event/1/",
            "catch": "",
            "description": "<p>イベント詳細</p>",
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**概要**: イベント詳細", result)

    def test_participation_status_with_limit(self):
        """accepted と limit がある場合、参加状況が出力される。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "accepted": 15, "limit": 30,
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**参加状況**: 15/30名", result)

    def test_participation_status_accepted_only(self):
        """limit が 0 で accepted だけある場合、定員なしで出力される。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "accepted": 10, "limit": 0,
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**参加状況**: 10名（定員なし）", result)

    def test_participation_status_omitted_when_zero(self):
        """accepted も limit も 0 の場合、参加状況行は出力されない。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "accepted": 0, "limit": 0,
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertNotIn("参加状況:", result)
        self.assertNotIn("**参加状況**:", result)

    def test_series_shown_when_present(self):
        """series（コミュニティ名）があれば出力される。"""
        events = [{
            "title": "イベント", "event_url": "https://connpass.com/event/1/",
            "series": "JAWS-UG Tokyo",
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**コミュニティ**: JAWS-UG Tokyo", result)

    def test_multiple_events_all_listed(self):
        """複数イベントがすべて出力される。"""
        events = [
            {"title": "イベントA", "event_url": "https://connpass.com/event/1/"},
            {"title": "イベントB", "event_url": "https://connpass.com/event/2/"},
            {"title": "イベントC", "event_url": "https://connpass.com/event/3/"},
        ]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("イベントA", result)
        self.assertIn("イベントB", result)
        self.assertIn("イベントC", result)

    def test_title_is_missing_uses_placeholder(self):
        """title が None または空の場合はプレースホルダーを使う。"""
        events = [{"title": None, "event_url": "https://connpass.com/event/1/"}]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("（タイトルなし）", result)

    def test_fields_separated_by_blank_lines(self):
        """各フィールド間に空行（二重改行）が入る。"""
        events = [{
            "title": "テストイベント",
            "event_url": "https://connpass.com/event/1/",
            "series": "JAWS-UG Tokyo",
            "started_at": "2026/05/15 19:00",
            "place": "東京都渋谷区",
            "catch": "テスト概要",
            "accepted": 10,
            "limit": 30,
        }]
        result = du._build_connpass_section_scripted(events)
        self.assertIn("**[テストイベント](https://connpass.com/event/1/)**\n\n**コミュニティ**", result)
        self.assertIn("**コミュニティ**: JAWS-UG Tokyo\n\n**開催日時**", result)
        self.assertIn("**開催日時**: 2026/05/15 19:00\n\n**場所**", result)
        self.assertIn("**場所**: 東京都渋谷区\n\n**概要**", result)
        self.assertIn("**概要**: テスト概要\n\n**参加状況**", result)


class TestGenerateCommunitySectionHybrid(unittest.TestCase):
    """_generate_community_section() のテスト（ハイブリッド生成）"""

    def _get_community_def(self) -> dict:
        return next(s for s in du.SECTION_DEFINITIONS if s["key"] == "community")

    def _make_client(self, content: str = "### 📝 参加レポート・イベント宣伝まとめ\n\n### レポートA\n**要約**: ...\n**リンク**: [A](https://example.com/a)"):
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        client.chat.completions.create.return_value.choices = [choice]
        return client

    def test_connpass_part_scripted_no_llm_call_for_events(self):
        """connpass イベント部分はスクリプト生成で LLM を呼ばない。"""
        section_def = self._get_community_def()
        events = [{"title": "Azure勉強会", "event_url": "https://connpass.com/event/1/"}]
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, events, [])

        # event_reports が空なので LLM は呼ばれない
        client.chat.completions.create.assert_not_called()
        # connpass イベントがスクリプトで出力される
        self.assertIn("Azure勉強会", result)
        self.assertIn("connpass.com/event/1/", result)

    def test_llm_called_once_for_event_reports(self):
        """event_reports がある場合、LLM が 1 回呼ばれる。"""
        section_def = self._get_community_def()
        event_reports = [{"title": "勉強会レポート", "url": "https://zenn.dev/post/1"}]
        client = self._make_client()

        du._generate_community_section(client, "gpt-4o", section_def, [], event_reports)

        client.chat.completions.create.assert_called_once()

    def test_empty_event_reports_no_llm_call(self):
        """event_reports が空の場合、LLM は呼ばれない。"""
        section_def = self._get_community_def()
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, [], [])

        client.chat.completions.create.assert_not_called()
        # 「情報なし」メッセージが含まれる
        self.assertIn("参加レポート情報はありません", result)

    def test_output_contains_section_header(self):
        """出力にセクションヘッダーが含まれる。"""
        section_def = self._get_community_def()
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, [], [])

        self.assertIn(section_def["header"], result)

    def test_output_contains_connpass_subsection(self):
        """出力に 📅 サブセクションが含まれる。"""
        section_def = self._get_community_def()
        events = [{"title": "イベントA", "event_url": "https://connpass.com/event/1/"}]
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, events, [])

        self.assertIn("### 📅 申し込み受付中のイベント", result)

    def test_output_contains_reports_subsection(self):
        """出力に 📝 サブセクションが含まれる（空でも）。"""
        section_def = self._get_community_def()
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, [], [])

        self.assertIn("📝 参加レポート", result)

    def test_llm_output_header_stripped(self):
        """LLM が誤って ## ヘッダーを出力した場合は除去される。"""
        section_def = self._get_community_def()
        event_reports = [{"title": "レポート", "url": "https://zenn.dev/1"}]
        llm_output = "## 5. コミュニティイベント情報（東京・神奈川）\n\n### 📝 参加レポート・イベント宣伝まとめ\n内容"
        client = self._make_client(llm_output)

        result = du._generate_community_section(client, "gpt-4o", section_def, [], event_reports)

        # ## ヘッダーは1回だけ（_generate_community_section が追加する分）
        self.assertEqual(result.count(section_def["header"]), 1)

    def test_event_urls_not_hallucinated(self):
        """スクリプト生成のため、connpass イベント URL はソースデータと完全一致する。"""
        section_def = self._get_community_def()
        events = [
            {"title": "テストイベント", "event_url": "https://connpass.com/event/999/"},
        ]
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, events, [])

        # 出力 URL がソースデータと完全一致
        self.assertIn("https://connpass.com/event/999/", result)
        # LLM が別の URL を作ることはない（スクリプト生成のため）
        self.assertNotIn("https://connpass.com/event/000/", result)

    def test_trailing_separator_stripped_from_llm_output(self):
        """LLM が末尾に「---」を出力した場合は除去される。"""
        section_def = self._get_community_def()
        event_reports = [{"title": "レポート", "url": "https://zenn.dev/1"}]
        llm_output = "### 📝 参加レポート・イベント宣伝まとめ\n\n### レポートA\n**要約**: ...\n**リンク**: [A](https://example.com/a)\n\n---"
        client = self._make_client(llm_output)

        result = du._generate_community_section(client, "gpt-4o", section_def, [], event_reports)

        # 末尾の「---」は除去されている
        self.assertFalse(result.rstrip().endswith("---"))

    def test_connpass_events_use_no_dash_subitem_format(self):
        """connpass イベントのサブアイテムに「- 」プレフィックスを使わない。"""
        section_def = self._get_community_def()
        events = [{
            "title": "テストイベント",
            "event_url": "https://connpass.com/event/1/",
            "started_at": "2026/05/15 19:00",
            "place": "東京都渋谷区",
            "series": "JAWS-UG",
            "catch": "概要テキスト",
            "accepted": 10,
            "limit": 30,
        }]
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, events, [])

        # サブアイテムに「  - 」プレフィックスがないこと
        self.assertNotIn("  - コミュニティ:", result)
        self.assertNotIn("  - 開催日時:", result)
        self.assertNotIn("  - 場所:", result)
        self.assertNotIn("  - 概要:", result)
        self.assertNotIn("  - 参加状況:", result)
        # フィールド内容は含まれる
        self.assertIn("**コミュニティ**: JAWS-UG", result)
        self.assertIn("**開催日時**: 2026/05/15 19:00", result)

    def test_multiple_connpass_events_separated_by_horizontal_rule(self):
        """複数の connpass イベントが「---」で区切られる。"""
        section_def = self._get_community_def()
        events = [
            {"title": "イベントA", "event_url": "https://connpass.com/event/1/"},
            {"title": "イベントB", "event_url": "https://connpass.com/event/2/"},
        ]
        client = self._make_client()

        result = du._generate_community_section(client, "gpt-4o", section_def, events, [])

        connpass_part = result.split("### 📝")[0]

        # connpass セクション内に 2 イベントが含まれる
        self.assertIn("イベントA", connpass_part)
        self.assertIn("イベントB", connpass_part)
        # 区切りは 2 件なら 1 回だけ
        self.assertEqual(connpass_part.count("---"), 1)
        # 区切りがイベントAとイベントBの間にある
        self.assertLess(connpass_part.index("イベントA"), connpass_part.index("---"))
        self.assertLess(connpass_part.index("---"), connpass_part.index("イベントB"))
        # 末尾の「---」は存在しない（イベントセクション内）
        self.assertFalse(connpass_part.rstrip().endswith("---"))


class TestFetchFeedMaxAgeDaysDailyUpdate(unittest.TestCase):
    """_fetch_feed() の MAX_ARTICLE_AGE_DAYS フィルタリングのテスト"""

    def _time_tuple(self, dt: datetime):
        return dt.timetuple()[:6]

    def _make_feed(self, entries):
        mock_feed = MagicMock()
        mock_entries = []
        for e in entries:
            entry = MagicMock()
            entry.get.side_effect = lambda key, default="", _e=e: _e.get(key, default)
            entry.published_parsed = e.get("published_parsed")
            entry.updated_parsed = e.get("updated_parsed")
            entry.link = e.get("link", "https://example.com/article")
            mock_entries.append(entry)
        mock_feed.entries = mock_entries
        return mock_feed

    def _run(self, entries, since):
        mock_resp = MagicMock()
        mock_resp.content = b""
        mock_feed = self._make_feed(entries)
        with (patch.object(ags.requests, "get", return_value=mock_resp),
              patch.object(ags.feedparser, "parse", return_value=mock_feed),
              patch.object(ags, "_resolve_google_news_url", side_effect=lambda u: u)):
            return du._fetch_feed("https://feed.example.com/rss", since)

    def test_article_older_than_max_age_days_is_excluded(self):
        """MAX_ARTICLE_AGE_DAYS より古い記事は since 以降であっても除外される。"""
        since = datetime.now(timezone.utc) - timedelta(days=du.MAX_ARTICLE_AGE_DAYS + 10)
        very_old = datetime.now(timezone.utc) - timedelta(days=du.MAX_ARTICLE_AGE_DAYS + 1)
        entries = [
            {
                "title": "Very Old Article",
                "link": "https://example.com/veryold",
                "published_parsed": self._time_tuple(very_old),
                "updated_parsed": None,
                "summary": "",
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(
            len(result), 0,
            f"MAX_ARTICLE_AGE_DAYS ({du.MAX_ARTICLE_AGE_DAYS}) より古い記事は除外されるべき",
        )

    def test_article_within_max_age_days_is_included(self):
        """MAX_ARTICLE_AGE_DAYS 以内かつ since 以降の記事は含まれる。"""
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        fresh = datetime.now(timezone.utc) - timedelta(minutes=30)
        entries = [
            {
                "title": "Fresh Article",
                "link": "https://example.com/fresh",
                "published_parsed": self._time_tuple(fresh),
                "updated_parsed": None,
                "summary": "",
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Fresh Article")

    def test_max_article_age_days_constant_is_30(self):
        """MAX_ARTICLE_AGE_DAYS は 30 日に設定されている。"""
        self.assertEqual(du.MAX_ARTICLE_AGE_DAYS, 30)


class TestLoadPreviousDayEventUrls(unittest.TestCase):
    """_load_previous_day_event_urls() のテスト"""

    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_md(self, date_str: str, content: str) -> None:
        path = os.path.join(self.tmp_dir, f"{date_str}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_returns_empty_set_when_file_missing(self):
        """前日のファイルが存在しない場合は空集合を返す。"""
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertEqual(result, set())

    def test_extracts_urls_from_markdown_links(self):
        """マークダウンリンク形式の URL を正しく抽出する。"""
        self._write_md("20260430", (
            "**[Python 勉強会](https://connpass.com/event/111/)**\n\n"
            "**[AI ハンズオン](https://connpass.com/event/222/)**\n"
        ))
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/111/", result)
        self.assertIn("https://connpass.com/event/222/", result)

    def test_returns_empty_set_when_no_links(self):
        """リンクが含まれない場合は空集合を返す。"""
        self._write_md("20260430", "本文のみ、リンクなし")
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertEqual(result, set())

    def test_date_previous_day_calculation(self):
        """前日の日付ファイルを正しく参照する（月をまたぐ場合も含む）。"""
        # 5/1 → 前日は 4/30
        self._write_md("20260430", "[title](https://connpass.com/event/100/)")
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/100/", result)
        # 当日ファイルは参照しない
        self._write_md("20260501", "[title](https://connpass.com/event/999/)")
        result2 = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertNotIn("https://connpass.com/event/999/", result2)

    def test_month_boundary_previous_day(self):
        """月初（例: 5/1 → 前日は 4/30）のファイル名が正しく解決される。"""
        self._write_md("20260430", "[ev](https://connpass.com/event/50/)")
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/50/", result)

    def test_excludes_non_connpass_urls(self):
        """connpass のイベント URL は抽出し、それ以外の URL はフィルタされて返されない。"""
        self._write_md("20260430", (
            "[connpass ev](https://connpass.com/event/111/)\n"
            "[subdomain connpass ev](https://foo.connpass.com/event/123/)\n"
            "[azure](https://azure.microsoft.com/updates/)\n"
            "[github](https://github.com/org/repo)\n"
        ))
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/111/", result)
        self.assertIn("https://foo.connpass.com/event/123/", result)
        self.assertNotIn("https://azure.microsoft.com/updates/", result)
        self.assertNotIn("https://github.com/org/repo", result)

    def test_collects_urls_from_multiple_past_days(self):
        """直近5日間の複数ファイルから URL を合算して返す。"""
        self._write_md("20260430", "[ev1](https://connpass.com/event/1/)")
        self._write_md("20260429", "[ev2](https://connpass.com/event/2/)")
        self._write_md("20260428", "[ev3](https://connpass.com/event/3/)")
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/1/", result)
        self.assertIn("https://connpass.com/event/2/", result)
        self.assertIn("https://connpass.com/event/3/", result)

    def test_includes_url_from_day5_but_not_day6(self):
        """5日前の URL は含まれるが、6日前の URL は含まれない。"""
        self._write_md("20260426", "[ev5](https://connpass.com/event/5/)")   # 5日前
        self._write_md("20260425", "[ev6](https://connpass.com/event/6/)")   # 6日前
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/5/", result,
                      "5日前の URL は含まれるべき")
        self.assertNotIn("https://connpass.com/event/6/", result,
                         "6日前の URL は含まれてはならない")

    def test_partial_files_missing_still_collects_available(self):
        """一部の日にファイルが存在しなくてもエラーにならず、存在する日の URL を返す。"""
        # 20260430 (1日前) と 20260428 (3日前) のみ作成し、他は欠落
        self._write_md("20260430", "[ev1](https://connpass.com/event/10/)")
        self._write_md("20260428", "[ev3](https://connpass.com/event/30/)")
        result = du._load_previous_day_event_urls("20260501", self.tmp_dir)
        self.assertIn("https://connpass.com/event/10/", result)
        self.assertIn("https://connpass.com/event/30/", result)

    def test_custom_days_parameter(self):
        """days パラメータで遡る日数を変更できる。"""
        self._write_md("20260430", "[ev1](https://connpass.com/event/1/)")  # 1日前
        self._write_md("20260429", "[ev2](https://connpass.com/event/2/)")  # 2日前
        self._write_md("20260428", "[ev3](https://connpass.com/event/3/)")  # 3日前
        # days=1 → 1日前のみ
        result1 = du._load_previous_day_event_urls("20260501", self.tmp_dir, days=1)
        self.assertIn("https://connpass.com/event/1/", result1)
        self.assertNotIn("https://connpass.com/event/2/", result1)
        # days=2 → 1〜2日前
        result2 = du._load_previous_day_event_urls("20260501", self.tmp_dir, days=2)
        self.assertIn("https://connpass.com/event/1/", result2)
        self.assertIn("https://connpass.com/event/2/", result2)
        self.assertNotIn("https://connpass.com/event/3/", result2)

class TestDeprioritizeRepeatedEvents(unittest.TestCase):
    """_deprioritize_repeated_events() のテスト"""

    def _make_event(self, event_id: int, started_at: str = "") -> dict:
        return {
            "title": f"イベント {event_id}",
            "event_url": f"https://connpass.com/event/{event_id}/",
            "started_at": started_at,
        }

    def test_repeated_events_moved_to_end(self):
        """前日にあった URL を持つイベントはリストの末尾に移動する。"""
        events = [
            self._make_event(1),
            self._make_event(2),
            self._make_event(3),
        ]
        prev_urls = {"https://connpass.com/event/2/"}
        result = du._deprioritize_repeated_events(events, prev_urls)
        self.assertEqual(result[0]["event_url"], "https://connpass.com/event/1/")
        self.assertEqual(result[1]["event_url"], "https://connpass.com/event/3/")
        self.assertEqual(result[2]["event_url"], "https://connpass.com/event/2/")

    def test_no_repeated_events_order_unchanged(self):
        """前日に重複がない場合は元の順序を維持する。"""
        events = [self._make_event(i) for i in range(1, 4)]
        prev_urls = {"https://connpass.com/event/99/"}
        result = du._deprioritize_repeated_events(events, prev_urls)
        for i, e in enumerate(result):
            self.assertEqual(e["event_url"], events[i]["event_url"])

    def test_all_repeated_events_order_maintained(self):
        """すべて重複している場合は元の順序を維持する。"""
        events = [self._make_event(i) for i in range(1, 4)]
        prev_urls = {e["event_url"] for e in events}
        result = du._deprioritize_repeated_events(events, prev_urls)
        for i, e in enumerate(result):
            self.assertEqual(e["event_url"], events[i]["event_url"])

    def test_empty_events_returns_empty(self):
        """空リストに対して空リストを返す。"""
        result = du._deprioritize_repeated_events([], {"https://connpass.com/event/1/"})
        self.assertEqual(result, [])

    def test_empty_prev_urls_order_unchanged(self):
        """prev_event_urls が空集合の場合は元の順序を維持する。"""
        events = [self._make_event(i) for i in range(1, 4)]
        result = du._deprioritize_repeated_events(events, set())
        for i, e in enumerate(result):
            self.assertEqual(e["event_url"], events[i]["event_url"])

    def test_total_event_count_unchanged(self):
        """リスト内のイベント総数は変化しない。"""
        events = [self._make_event(i) for i in range(1, 6)]
        prev_urls = {
            "https://connpass.com/event/1/",
            "https://connpass.com/event/3/",
        }
        result = du._deprioritize_repeated_events(events, prev_urls)
        self.assertEqual(len(result), len(events))

    def test_new_events_precede_repeated_events(self):
        """新規イベントは常に重複イベントより前に来る。"""
        events = [
            self._make_event(10, "2026/05/01 10:00"),
            self._make_event(20, "2026/05/02 10:00"),  # 重複
            self._make_event(30, "2026/05/03 10:00"),
            self._make_event(40, "2026/05/04 10:00"),  # 重複
        ]
        prev_urls = {
            "https://connpass.com/event/20/",
            "https://connpass.com/event/40/",
        }
        result = du._deprioritize_repeated_events(events, prev_urls)
        new_part = [e for e in result if e["event_url"] not in prev_urls]
        repeated_part = [e for e in result if e["event_url"] in prev_urls]
        # 新規イベントは先頭から連続して並ぶ
        self.assertEqual(result[: len(new_part)], new_part)
        self.assertEqual(result[len(new_part) :], repeated_part)


if __name__ == "__main__":
    unittest.main()
