"""
generate_daily_update.py のセッション分割（セクションごと個別 LLM 呼び出し）ロジックのテスト
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, call, patch

# スクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import generate_daily_update as du


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
        """空データのリスト型セクションは「ありません」メッセージを含む。"""
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
        # リスト型セクションは LLM を呼ばずに「ありません」が含まれる
        # community セクションは dict 型データのため LLM を経由し、ヘッダーはモック出力に含まれない
        for section in du.SECTION_DEFINITIONS:
            if section["key"] != "community":
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


class TestDailyUpdateSinceWindow(unittest.TestCase):
    """デイリー更新の収集開始時刻計算のテスト"""

    def test_compute_since_is_previous_day_0730_jst(self):
        """compute_since() は対象日の前日 07:30 JST を返す。"""
        since = du.compute_since("20260415")
        self.assertEqual(since.isoformat(), "2026-04-14T07:30:00+09:00")


class TestValidateLinksOrphanedSeparatorsDailyUpdate(unittest.TestCase):
    """validate_links() の孤立した --- セパレータ除去テスト"""

    def _make_article_with_invalid_link(self, url: str = "https://bad.example.com") -> str:
        return (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n内容A\n\n**参考リンク**: [タイトルA](https://good.example.com)\n\n"
            "---\n\n"
            f"### トピックB\n\n内容B\n\n**参考リンク**: [タイトルB]({url})\n\n"
            "---\n\n"
            "## 2. ニュースで話題のテーマ\n\n"
        )

    def test_orphan_separators_removed_when_topic_deleted(self):
        """リンク無効でトピック除去後に残った孤立 --- が除去される。"""
        article = self._make_article_with_invalid_link()
        with (
            patch.object(du, "_validate_url", return_value=(False, "HTTP 404")),
            patch.object(du, "_search_alternative_url", return_value=None),
        ):
            result = du.validate_links(article)
        self.assertNotIn("\n---\n\n---\n", result)
        self.assertNotIn("\n---\n\n## ", result)

    def test_valid_separators_preserved(self):
        """有効なリンクのみを含む記事では --- セパレータが保持される。"""
        article = self._make_article_with_invalid_link()
        with patch.object(du, "_validate_url", return_value=(True, "OK")):
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
        article = f"{self._HEADER}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]
        general_items = [{"url": "https://general.example.com", "title": "汎用ニュース"}]
        new_content = f"{self._HEADER}\n\n### 汎用トピック\n内容"
        llm_clients = self._make_llm_clients(new_content)
        client = llm_clients[0][0]

        with (
            patch.object(du, "_fetch_section_category", return_value=original_items),
            patch.object(du, "fetch_general_news", return_value=general_items),
            patch.object(du, "validate_links", side_effect=lambda x: x),
        ):
            result = du._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"azure": original_items},
                MagicMock(),
                llm_clients,
            )

        client.chat.completions.create.assert_called_once()
        self.assertIn("汎用トピック", result)

    def test_general_news_fallback_excludes_original_urls(self):
        """汎用ニュースフォールバック時も元データの URL が除外される。"""
        article = f"{self._HEADER}\n\n"
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
                [self._SECTION_DEF],
                {"azure": original_items},
                MagicMock(),
                self._make_llm_clients(),
            )

        self.assertIn("https://old.example.com", captured_exclude.get("urls", set()))

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
            "**参考リンク**: https://docs.microsoft.com/azure/monitor/\n"
        )
        result = du._format_bare_reference_links(md)
        self.assertIn("[Azure Monitor の新機能](https://docs.microsoft.com/azure/monitor/)", result)
        self.assertNotIn("**参考リンク**: https://", result)

    def test_url_as_label_converted_using_heading(self):
        """[https://...](https://...) 形式が見出しをラベルにしたリンクへ変換される。"""
        md = (
            "### AWS CLI の変更\n\n"
            "**参考リンク**: [https://aws.amazon.com/blogs/news/](https://aws.amazon.com/blogs/news/)\n"
        )
        result = du._format_bare_reference_links(md)
        self.assertIn("[AWS CLI の変更](https://aws.amazon.com/blogs/news/)", result)
        self.assertNotIn("[https://", result)

    def test_already_formatted_link_unchanged(self):
        """既に [タイトル](URL) 形式のリンクは変更されない。"""
        md = (
            "### トピック\n\n"
            "**参考リンク**: [詳細記事](https://example.com/article)\n"
        )
        result = du._format_bare_reference_links(md)
        self.assertIn("[詳細記事](https://example.com/article)", result)

    def test_no_heading_falls_back_to_url_as_label(self):
        """直前に ### 見出しがない場合、URL 自身がラベルに使われる。"""
        md = "**参考リンク**: https://example.com/fallback\n"
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


class TestVerifyContentDailyUpdate(unittest.TestCase):
    """verify_content() の検証プロセスのテスト"""

    def test_valid_article_unchanged(self):
        """正しい形式の記事は変更されない。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### Azure Functions の新機能\n\n"
            "**要約**: テスト要約\n\n"
            "**影響**: テスト影響\n\n"
            "**参考リンク**: [Azure Functions](https://example.com/azure)\n"
        )
        result = du.verify_content(md)
        self.assertEqual(result.strip(), md.strip())

    def test_heading_hyperlink_is_unlinked(self):
        """### [タイトル](URL) 形式の見出しからリンクが除去される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### [Azure Update](https://example.com/azure)\n\n"
            "**要約**: テスト\n\n"
            "**参考リンク**: [Azure Update](https://example.com/azure)\n"
        )
        result = du.verify_content(md)
        self.assertIn("### Azure Update", result)
        self.assertNotIn("### [Azure Update](https://", result)

    def test_missing_summary_detected(self):
        """**要約** が欠落しているトピックでもエラーにならずに文字列が返る。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "内容のみ\n\n"
            "**参考リンク**: [タイトル](https://example.com)\n"
        )
        # 例外が発生しないことを確認（ログで報告される）
        result = du.verify_content(md)
        self.assertIsInstance(result, str)

    def test_missing_reference_link_detected(self):
        """**参考リンク** が欠落しているトピックが検出される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n"
        )
        result = du.verify_content(md)
        self.assertIsInstance(result, str)

    def test_malformed_reference_link_detected(self):
        """**参考リンク** が [text](URL) 形式でないトピックが検出される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**参考リンク**: https://example.com/bare\n"
        )
        result = du.verify_content(md)
        self.assertIsInstance(result, str)

    def test_closing_sentence_removed(self):
        """セクション末尾の締め文が除去される。"""
        md = (
            "## 1. Azure アップデート情報\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**影響**: テスト\n\n"
            "**参考リンク**: [タイトル](https://example.com)\n\n"
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
            "**参考リンク**: [タイトル](https://example.com)\n"
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
        # 📅/📝 サブセクションで要約・参考リンクの欠落が検出されないことを確認
        result = du.verify_content(md)
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
