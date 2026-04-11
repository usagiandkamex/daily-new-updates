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
        section = self._get_section("itops")
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
            itops_news=[{"title": "e"}],
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
            itops_news=[],
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
            itops_news=[],
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
            itops_news=[{"title": "e"}],
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
            itops_news=[{"title": "e"}],
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


if __name__ == "__main__":
    unittest.main()
