"""
generate_smallchat.py のセッション分割（セクションごと個別 LLM 呼び出し）ロジックのテスト
"""

import sys
import os
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# スクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import generate_smallchat as sc
import article_generator_shared as ags


def _make_client(content: str = "生成テキスト"):
    """LLM クライアントのモックを作成する。"""
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    client.chat.completions.create.return_value.choices = [choice]
    return client


class TestBuildSectionPromptSmallchat(unittest.TestCase):
    """_build_section_prompt() のテスト"""

    def _get_section(self, key: str) -> dict:
        for s in sc.SECTION_DEFINITIONS:
            if s["key"] == key:
                return s
        raise KeyError(key)

    def test_data_label_in_prompt(self):
        """data_label がプロンプトに含まれる。"""
        section = self._get_section("microsoft")
        data = [{"title": "MSニュース", "url": "https://example.com"}]
        prompt = sc._build_section_prompt(section, data)
        self.assertIn(section["data_label"], prompt)

    def test_data_content_in_prompt(self):
        """データの内容がプロンプトに含まれる。"""
        section = self._get_section("ai")
        data = [{"title": "AIの最新動向"}]
        prompt = sc._build_section_prompt(section, data)
        self.assertIn("AIの最新動向", prompt)

    def test_empty_list_returns_prompt(self):
        """空データでもプロンプトが生成される。"""
        section = self._get_section("security")
        prompt = sc._build_section_prompt(section, [])
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)

    def test_instruction_included(self):
        """instruction テキストがプロンプトに含まれる。"""
        section = self._get_section("azure")
        prompt = sc._build_section_prompt(section, [])
        self.assertIn(section["instruction"], prompt)

    def test_since_adds_date_notice(self):
        """since を指定するとプロンプトに対象期間の注意事項が追加される。"""
        from datetime import timezone
        since = datetime(2026, 4, 1, 3, 0, tzinfo=timezone.utc)
        section = self._get_section("microsoft")
        prompt = sc._build_section_prompt(section, [], since=since)
        self.assertIn("対象期間", prompt)
        self.assertIn("JST", prompt)

    def test_no_since_omits_date_notice(self):
        """since を指定しない場合は対象期間の注意事項が含まれない。"""
        section = self._get_section("microsoft")
        prompt = sc._build_section_prompt(section, [], since=None)
        self.assertNotIn("対象期間", prompt)


class TestGenerateSectionSmallchat(unittest.TestCase):
    """generate_section() のテスト"""

    def _get_section(self, key: str) -> dict:
        for s in sc.SECTION_DEFINITIONS:
            if s["key"] == key:
                return s
        raise KeyError(key)

    def test_calls_llm_once_per_section(self):
        """1 セクションにつき LLM を 1 回だけ呼び出す。"""
        client = _make_client("## 1. Microsoft セクション")
        section = self._get_section("microsoft")
        result = sc.generate_section(client, "gpt-4o", section, [{"title": "記事1"}])
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(result, "## 1. Microsoft セクション")

    def test_uses_section_system_prompt(self):
        """システムプロンプトにセクション固有のものが使われる。"""
        client = _make_client("出力")
        section = self._get_section("ai")
        sc.generate_section(client, "gpt-4o", section, [{"title": "記事1"}])
        call_kwargs = client.chat.completions.create.call_args
        messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
        system_msg = next(m for m in messages if m["role"] == "system")
        self.assertEqual(system_msg["content"], section["system"])

    def test_max_tokens_is_section_output_limit(self):
        """max_tokens に SECTION_MAX_OUTPUT_TOKENS が使われる。"""
        client = _make_client("出力")
        section = self._get_section("cloud")
        sc.generate_section(client, "gpt-4o", section, [{"title": "記事1"}])
        call_kwargs = client.chat.completions.create.call_args
        kwargs = call_kwargs[1] if call_kwargs[1] else {}
        self.assertEqual(kwargs.get("max_tokens"), sc.SECTION_MAX_OUTPUT_TOKENS)

    def test_trims_list_when_prompt_too_large(self):
        """プロンプトが上限を超えた場合、データリストが削減される。"""
        section = self._get_section("microsoft")
        big_item = {"title": "x" * 1000, "description": "y" * 1000}
        data = [dict(big_item) for _ in range(30)]
        original_len = len(data)

        client = _make_client("trimmed")
        sc.generate_section(client, "gpt-4o", section, data)
        self.assertLess(len(data), original_len)

    def test_stops_trimming_at_3_items(self):
        """データが3件以下になった場合はそれ以上削減しない。"""
        section = self._get_section("security")
        big_item = {"title": "x" * 5000, "description": "y" * 5000}
        data = [dict(big_item) for _ in range(3)]

        client = _make_client("output")
        sc.generate_section(client, "gpt-4o", section, data)
        self.assertEqual(len(data), 3)

    def test_result_is_stripped(self):
        """戻り値の前後の空白がトリムされている。"""
        client = _make_client("  前後に空白   ")
        section = self._get_section("itops")
        result = sc.generate_section(client, "gpt-4o", section, [{"title": "記事1"}])
        self.assertEqual(result, "前後に空白")

    def test_empty_list_returns_no_info_message_without_llm(self):
        """空データの場合は LLM を呼ばずに「ありません」メッセージを返す。"""
        client = _make_client("呼ばれないはず")
        section = self._get_section("microsoft")
        result = sc.generate_section(client, "gpt-4o", section, [])
        self.assertEqual(client.chat.completions.create.call_count, 0)
        self.assertIn(section["header"], result)
        self.assertIn("ありません", result)

    def test_empty_list_result_starts_with_section_header(self):
        """空データ時の戻り値はセクションヘッダーで始まる。"""
        client = _make_client("呼ばれないはず")
        for section in sc.SECTION_DEFINITIONS:
            result = sc.generate_section(client, "gpt-4o", section, [])
            self.assertTrue(
                result.startswith(section["header"]),
                f"セクション {section['key']} の空データ結果がヘッダーで始まっていない",
            )


class TestGenerateArticleSmallchat(unittest.TestCase):
    """generate_article() のテスト（セッション分割）"""

    def test_calls_llm_once_per_section(self):
        """generate_article は データがある SECTION_DEFINITIONS の数だけ LLM を呼び出す。"""
        client = _make_client("セクション出力")
        sc.generate_article(
            client, "gpt-4o", "20260401", "am",
            microsoft_news=[{"title": "a"}],
            ai_news=[{"title": "b"}],
            azure_news=[{"title": "c"}],
            security_news=[{"title": "d"}],
            cloud_news=[{"title": "e"}],
            itops_news=[{"title": "f"}],
            techblog_ja_news=[{"title": "g"}],
            techblog_en_news=[{"title": "h"}],
        )
        expected_calls = len(sc.SECTION_DEFINITIONS)
        self.assertEqual(client.chat.completions.create.call_count, expected_calls)

    def test_article_starts_with_date_header_am(self):
        """午前スロットの記事ヘッダーが正しい。"""
        client = _make_client("本文")
        result = sc.generate_article(
            client, "gpt-4o", "20260401", "am",
            microsoft_news=[], ai_news=[], azure_news=[],
            security_news=[], cloud_news=[], itops_news=[],
        )
        self.assertIn("# 2026/04/01 テクニカル雑談（午前）", result)

    def test_article_starts_with_date_header_pm(self):
        """午後スロットの記事ヘッダーが正しい。"""
        client = _make_client("本文")
        result = sc.generate_article(
            client, "gpt-4o", "20260401", "pm",
            microsoft_news=[], ai_news=[], azure_news=[],
            security_news=[], cloud_news=[], itops_news=[],
        )
        self.assertIn("# 2026/04/01 テクニカル雑談（午後）", result)

    def test_all_section_outputs_in_article(self):
        """各セクション出力が結合されて 1 つの記事になる。"""
        sections = sc.SECTION_DEFINITIONS
        client = MagicMock()
        responses = []
        for s in sections:
            choice = MagicMock()
            choice.message.content = f"  section_{s['key']}_output  "
            mock_resp = MagicMock()
            mock_resp.choices = [choice]
            responses.append(mock_resp)
        client.chat.completions.create.side_effect = responses

        result = sc.generate_article(
            client, "gpt-4o", "20260401", "am",
            microsoft_news=[{"title": "a"}],
            ai_news=[{"title": "b"}],
            azure_news=[{"title": "c"}],
            security_news=[{"title": "d"}],
            cloud_news=[{"title": "e"}],
            itops_news=[{"title": "f"}],
            techblog_ja_news=[{"title": "g"}],
            techblog_en_news=[{"title": "h"}],
        )
        for s in sections:
            self.assertIn(f"section_{s['key']}_output", result)

    def test_each_section_uses_independent_session(self):
        """各セクションが独立したシステムプロンプトで呼び出される（セッション分割の確認）。"""
        client = _make_client("出力")
        sc.generate_article(
            client, "gpt-4o", "20260401", "am",
            microsoft_news=[{"title": "a"}],
            ai_news=[{"title": "b"}],
            azure_news=[{"title": "c"}],
            security_news=[{"title": "d"}],
            cloud_news=[{"title": "e"}],
            itops_news=[{"title": "f"}],
            techblog_ja_news=[{"title": "g"}],
            techblog_en_news=[{"title": "h"}],
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
        self.assertEqual(len(unique_prompts), len(sc.SECTION_DEFINITIONS))


    def test_empty_sections_show_no_info_message(self):
        """空データの全セクションは「ありません」メッセージを含む。"""
        client = _make_client("呼ばれないはず")
        result = sc.generate_article(
            client, "gpt-4o", "20260401", "am",
            microsoft_news=[], ai_news=[], azure_news=[],
            security_news=[], cloud_news=[], itops_news=[],
        )
        self.assertEqual(client.chat.completions.create.call_count, 0)
        for section in sc.SECTION_DEFINITIONS:
            self.assertIn(section["header"], result,
                          f"セクション {section['key']} のヘッダーが記事に含まれない")
        self.assertIn("ありません", result)


class TestValidateLinksOrphanedSeparators(unittest.TestCase):
    """validate_links() でトピック除去後に残る孤立した --- の除去テスト"""

    def _run_validate_links_with_bad_urls(self, markdown: str, bad_urls: list[str]) -> str:
        """指定 URL を無効として validate_links を実行するヘルパー。"""
        def fake_validate(url: str):
            if url in bad_urls:
                return False, "HTTP 404"
            return True, "OK"

        with (patch.object(ags, "_validate_url", side_effect=fake_validate),
              patch.object(ags, "_search_alternative_url", return_value=None)):
            return sc.validate_links(markdown)

    def test_consecutive_separators_removed_when_all_topics_deleted(self):
        """全トピックが除去されたセクションから孤立した --- が除去される。"""
        markdown = (
            "## 4. クラウド（AWS / GCP / OCI）\n\n"
            "---\n\n"
            "### Topic 1\n\n"
            "**要約**: 内容1\n\n"
            "**リンク**: [Link](https://bad1.example.com)\n\n"
            "---\n\n"
            "### Topic 2\n\n"
            "**要約**: 内容2\n\n"
            "**リンク**: [Link](https://bad2.example.com)\n\n"
            "---\n\n"
            "## 5. セキュリティ\n"
        )
        result = self._run_validate_links_with_bad_urls(
            markdown, ["https://bad1.example.com", "https://bad2.example.com"]
        )
        # 除去後に --- が残っていないこと
        self.assertNotIn("---", result)

    def test_leading_separator_removed_when_first_topics_deleted(self):
        """先頭のトピックが除去された場合、セクションヘッダー直後の --- が除去される。"""
        markdown = (
            "## 1. Microsoft\n\n"
            "---\n\n"
            "### Removed Topic\n\n"
            "**要約**: 内容\n\n"
            "**リンク**: [Link](https://bad.example.com)\n\n"
            "---\n\n"
            "### Kept Topic\n\n"
            "**要約**: 残った内容\n\n"
            "**リンク**: [Link](https://good.example.com)\n"
        )
        result = self._run_validate_links_with_bad_urls(
            markdown, ["https://bad.example.com"]
        )
        # セクションヘッダーの直後に --- がないこと
        self.assertNotIn("## 1. Microsoft\n\n---", result)
        # 残ったトピックは保持されていること
        self.assertIn("Kept Topic", result)

    def test_valid_separator_between_kept_topics_is_preserved(self):
        """削除されなかったトピック間の --- は保持される。"""
        markdown = (
            "## 1. Microsoft\n\n"
            "### Removed Topic\n\n"
            "**要約**: 内容\n\n"
            "**リンク**: [Link](https://bad.example.com)\n\n"
            "---\n\n"
            "### Kept Topic 1\n\n"
            "**要約**: 内容1\n\n"
            "**リンク**: [Link](https://good1.example.com)\n\n"
            "---\n\n"
            "### Kept Topic 2\n\n"
            "**要約**: 内容2\n\n"
            "**リンク**: [Link](https://good2.example.com)\n"
        )
        result = self._run_validate_links_with_bad_urls(
            markdown, ["https://bad.example.com"]
        )
        # 残ったトピック間の --- は保持される
        self.assertIn("---", result)
        self.assertIn("Kept Topic 1", result)
        self.assertIn("Kept Topic 2", result)

    def test_no_change_when_no_topics_removed(self):
        """除去するトピックがない場合、コンテンツは変更されない。"""
        markdown = (
            "## 1. Microsoft\n\n"
            "### Topic 1\n\n"
            "**要約**: 内容\n\n"
            "**リンク**: [Link](https://good.example.com)\n"
        )
        result = self._run_validate_links_with_bad_urls(markdown, [])
        self.assertEqual(result, markdown)




class TestRegenerateEmptySections(unittest.TestCase):
    """_regenerate_empty_sections() のテスト"""

    _SECTION_DEF = next(s for s in sc.SECTION_DEFINITIONS if s["key"] == "cloud")
    _HEADER = _SECTION_DEF["header"]  # "## 4. クラウド（AWS / GCP / OCI）"

    def _make_llm_clients(self, content: str = "## 4. クラウド（AWS / GCP / OCI）\n\n### 新トピック\n\n内容"):
        client = _make_client(content)
        return [(client, "gpt-4o")]

    def test_empty_section_is_regenerated(self):
        """トピックのないセクションが再生成される。"""
        article = (
            "# Title\n\n"
            f"{self._HEADER}\n\n"
            "## 5. セキュリティ\n\n### 既存トピック\n内容\n"
        )
        new_content = f"{self._HEADER}\n\n### 新トピック\n\n**リンク**: https://new.example.com"
        llm_clients = self._make_llm_clients(new_content)
        new_items = [{"url": "https://new.example.com", "title": "新記事"}]
        extended_since = object()  # dummy; fetch_category is patched

        with (patch.object(sc, "fetch_category", return_value=new_items),
              patch.object(sc, "validate_links", side_effect=lambda x: x)):
            result = sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": []},
                extended_since,
                llm_clients,
            )

        self.assertIn("新トピック", result)

    def test_section_with_topics_is_not_regenerated(self):
        """トピックがあるセクションは再生成されない（LLM は呼ばれない）。"""
        article = (
            f"{self._HEADER}\n\n"
            "### 既存トピック\n\n**リンク**: https://good.example.com\n"
        )
        llm_clients = self._make_llm_clients()
        client = llm_clients[0][0]

        with patch.object(sc, "fetch_category", return_value=[]):
            sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": []},
                object(),
                llm_clients,
            )

        client.chat.completions.create.assert_not_called()

    def test_no_info_message_section_is_not_reprocessed(self):
        """「情報なし」メッセージが既に記載されているセクションは再処理されない。"""
        article = f"{self._HEADER}\n\n現在の対象期間に該当する情報はありません。\n"
        llm_clients = self._make_llm_clients()
        client = llm_clients[0][0]

        with patch.object(sc, "fetch_category", return_value=[]):
            sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": []},
                object(),
                llm_clients,
            )

        client.chat.completions.create.assert_not_called()

    def test_no_new_items_writes_no_info_message(self):
        """専用フィードも汎用フィードも新規データなければ LLM は呼ばれず、情報なしメッセージが記載される。"""
        article = f"{self._HEADER}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]
        llm_clients = self._make_llm_clients()
        client = llm_clients[0][0]

        # fetch_category は元データと同じ URL だけ返す → new_items = []
        # fetch_general_news も空リストを返す
        with (patch.object(sc, "fetch_category", return_value=original_items),
              patch.object(sc, "fetch_general_news", return_value=[])):
            result = sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": original_items},
                object(),
                llm_clients,
            )

        client.chat.completions.create.assert_not_called()
        self.assertIn("ありません", result)

    def test_no_category_items_falls_back_to_general_news(self):
        """専用フィードに新規データがなければ汎用ニュースにフォールバックして LLM を呼ぶ。"""
        article = f"{self._HEADER}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]
        general_items = [{"url": "https://general.example.com", "title": "汎用ニュース"}]
        new_content = f"{self._HEADER}\n\n### 汎用トピック\n内容"
        llm_clients = self._make_llm_clients(new_content)
        client = llm_clients[0][0]

        # fetch_category は既存 URL のみ → new_items = []
        # fetch_general_news は新規記事を返す
        with (patch.object(sc, "fetch_category", return_value=original_items),
              patch.object(sc, "fetch_general_news", return_value=general_items),
              patch.object(sc, "validate_links", side_effect=lambda x: x)):
            result = sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": original_items},
                object(),
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

        with (patch.object(sc, "fetch_category", return_value=original_items),
              patch.object(sc, "fetch_general_news", side_effect=fake_fetch_general_news)):
            sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": original_items},
                object(),
                self._make_llm_clients(),
            )

        self.assertIn("https://old.example.com", captured_exclude.get("urls", set()))

    def test_regenerated_section_links_are_validated(self):
        """再生成されたセクションのリンクも validate_links で検証される。"""
        article = f"{self._HEADER}\n\n"
        new_items = [{"url": "https://new.example.com", "title": "新記事"}]
        new_content = f"{self._HEADER}\n\n### 新トピック\n内容"
        llm_clients = self._make_llm_clients(new_content)

        validate_calls = []

        def fake_validate(md):
            validate_calls.append(md)
            return md

        with (patch.object(sc, "fetch_category", return_value=new_items),
              patch.object(sc, "validate_links", side_effect=fake_validate)):
            sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": []},
                object(),
                llm_clients,
            )

        self.assertTrue(any("新トピック" in c for c in validate_calls))

    def test_original_url_items_are_excluded_from_retry(self):
        """元データの URL を持つ記事は再生成に使わない（重複除外）。"""
        article = f"{self._HEADER}\n\n"
        original_items = [{"url": "https://old.example.com", "title": "既存"}]
        new_items = [
            {"url": "https://old.example.com", "title": "既存"},  # 除外される
            {"url": "https://new.example.com", "title": "新規"},   # 使われる
        ]
        new_content = f"{self._HEADER}\n\n### 新トピック\n内容"
        llm_clients = self._make_llm_clients(new_content)
        captured_data = []

        def fake_generate_section(client, model, section_def, data):
            captured_data.extend(data)
            return new_content

        with (patch.object(sc, "fetch_category", return_value=new_items),
              patch.object(sc, "validate_links", side_effect=lambda x: x),
              patch.object(sc, "generate_section", side_effect=fake_generate_section)):
            sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": original_items},
                object(),
                llm_clients,
            )

        urls_used = [item["url"] for item in captured_data]
        self.assertNotIn("https://old.example.com", urls_used)
        self.assertIn("https://new.example.com", urls_used)

    def test_empty_section_after_retry_validate_writes_no_info_message(self):
        """再生成後も validate_links でトピックが全除去された場合、情報なしメッセージが記載される。"""
        article = f"{self._HEADER}\n\n"
        new_items = [{"url": "https://new.example.com", "title": "新記事"}]
        # LLM はトピックを生成するが validate_links が全除去して ### がなくなる
        new_content_with_topics = f"{self._HEADER}\n\n### 新トピック\n内容"
        new_content_all_removed = f"{self._HEADER}\n\n"  # validate_links 後の状態
        llm_clients = self._make_llm_clients(new_content_with_topics)

        with (patch.object(sc, "fetch_category", return_value=new_items),
              patch.object(sc, "validate_links", return_value=new_content_all_removed)):
            result = sc._regenerate_empty_sections(
                article,
                [self._SECTION_DEF],
                {"cloud": []},
                object(),
                llm_clients,
            )

        self.assertIn("ありません", result)
        self.assertNotIn("新トピック", result)

    def test_official_only_section_skips_general_news_fallback(self):
        """official_only=True のセクション（Azure 等）は汎用ニュースへのフォールバックを行わない。"""
        azure_def = next(s for s in sc.SECTION_DEFINITIONS if s["key"] == "azure")
        header = azure_def["header"]
        article = f"{header}\n\n"
        original_items = [{"url": "https://old.azure.example.com", "title": "既存"}]

        with (
            patch.object(sc, "fetch_category", return_value=original_items),
            patch.object(sc, "fetch_general_news") as mock_general,
        ):
            result = sc._regenerate_empty_sections(
                article,
                [azure_def],
                {"azure": original_items},
                object(),
                self._make_llm_clients(),
            )

        mock_general.assert_not_called()
        self.assertIn("現在の対象期間に該当する情報はありません。", result)


class TestFormatBareReferenceLinksSmallchat(unittest.TestCase):
    """_format_bare_reference_links() のテスト"""

    def test_bare_url_converted_using_heading(self):
        """裸の URL が直近の ### 見出しをラベルにしたハイパーリンクへ変換される。"""
        md = (
            "### cuBLAS のバグ\n\n"
            "**要約**: 内容\n\n"
            "**リンク**: https://www.reddit.com/r/MachineLearning/comments/abc/\n"
        )
        result = sc._format_bare_reference_links(md)
        self.assertIn("[cuBLAS のバグ](https://www.reddit.com/r/MachineLearning/comments/abc/)", result)
        self.assertNotIn("**リンク**: https://", result)

    def test_url_as_label_converted_using_heading(self):
        """[https://...](https://...) 形式が見出しをラベルにしたリンクへ変換される。"""
        md = (
            "### Amazon EC2 vs Azure\n\n"
            "**リンク**: [https://www.prnewswire.com/news.html](https://www.prnewswire.com/news.html)\n"
        )
        result = sc._format_bare_reference_links(md)
        self.assertIn("[Amazon EC2 vs Azure](https://www.prnewswire.com/news.html)", result)
        self.assertNotIn("[https://", result)

    def test_already_formatted_link_unchanged(self):
        """既に [タイトル](URL) 形式のリンクは変更されない。"""
        md = (
            "### トピック\n\n"
            "**リンク**: [Read More](https://example.com/article)\n"
        )
        result = sc._format_bare_reference_links(md)
        self.assertIn("[Read More](https://example.com/article)", result)

    def test_no_heading_falls_back_to_url_as_label(self):
        """直前に ### 見出しがない場合、URL 自身がラベルに使われる。"""
        md = "**リンク**: https://example.com/fallback\n"
        result = sc._format_bare_reference_links(md)
        self.assertIn("[https://example.com/fallback](https://example.com/fallback)", result)


class TestSectionDefinitionsSmallchat(unittest.TestCase):
    """SECTION_DEFINITIONS の構造テスト"""

    def test_all_sections_have_required_keys(self):
        """各セクション定義に必須キーが存在する。"""
        required_keys = {"key", "system", "instruction", "data_label", "header"}
        for section in sc.SECTION_DEFINITIONS:
            for k in required_keys:
                self.assertIn(k, section, f"セクション {section.get('key')} に '{k}' がない")

    def test_section_keys_match_max_input_chars(self):
        """SECTION_MAX_INPUT_CHARS に全セクションキーのエントリが存在する。"""
        for section in sc.SECTION_DEFINITIONS:
            self.assertIn(
                section["key"], sc.SECTION_MAX_INPUT_CHARS,
                f"SECTION_MAX_INPUT_CHARS にキー '{section['key']}' がない"
            )

    def test_eight_sections_defined(self):
        """8 セクション（Microsoft・AI・Azure・クラウド・セキュリティ・IT運用管理・日本企業テックブログ・海外企業テックブログ）が定義されている。"""
        keys = [s["key"] for s in sc.SECTION_DEFINITIONS]
        self.assertEqual(len(keys), 8)
        for expected in ["microsoft", "ai", "azure", "cloud", "security", "itops", "techblog_ja", "techblog_en"]:
            self.assertIn(expected, keys)

    def test_max_output_tokens_positive(self):
        """SECTION_MAX_OUTPUT_TOKENS は正の整数。"""
        self.assertIsInstance(sc.SECTION_MAX_OUTPUT_TOKENS, int)
        self.assertGreater(sc.SECTION_MAX_OUTPUT_TOKENS, 0)

    def test_instructions_enforce_heading_and_no_section_closing(self):
        """各 instruction に見出し非リンク・セクション締め禁止の指示が含まれる。"""
        for section in sc.SECTION_DEFINITIONS:
            instruction = section["instruction"]
            self.assertIn("見出し（###）自体はハイパーリンクにせず", instruction)
            self.assertIn("締めの文章は入れないでください", instruction)


class TestFetchFeedDateFilter(unittest.TestCase):
    """_fetch_feed() の日付フィルタリングのテスト"""

    def _make_feed(self, entries: list[dict]):
        """feedparser.FeedParserDict 相当のモックを返す。"""
        mock_feed = MagicMock()
        mock_entries = []
        for e in entries:
            entry = MagicMock()
            entry.get.side_effect = lambda key, default="", _e=e: _e.get(key, default)
            # published_parsed / updated_parsed
            entry.published_parsed = e.get("published_parsed")
            entry.updated_parsed = e.get("updated_parsed")
            # link → article URL
            entry.link = e.get("link", "https://example.com/article")
            mock_entries.append(entry)
        mock_feed.entries = mock_entries
        return mock_feed

    def _run(self, entries: list[dict], since: datetime) -> list[dict]:
        """requests と feedparser をモックして _fetch_feed を呼ぶ。"""
        mock_resp = MagicMock()
        mock_resp.content = b""
        mock_feed = self._make_feed(entries)
        with (patch.object(sc.requests, "get", return_value=mock_resp),
              patch.object(sc.feedparser, "parse", return_value=mock_feed),
              patch.object(ags, "_resolve_google_news_url", side_effect=lambda u: u)):
            return sc._fetch_feed("https://feed.example.com/rss", since)

    def _time_tuple(self, dt: datetime):
        """datetime を time.struct_time タプル（6 要素）に変換する。"""
        return dt.timetuple()[:6]

    def test_recent_article_with_date_is_included(self):
        """since より新しい日付を持つ記事は含まれる。"""
        since = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)
        recent = datetime(2026, 4, 12, 6, 0, tzinfo=timezone.utc)
        entries = [
            {
                "title": "Recent Article",
                "link": "https://example.com/recent",
                "published_parsed": self._time_tuple(recent),
                "updated_parsed": None,
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Recent Article")

    def test_article_older_than_since_is_excluded(self):
        """`since` より古い日付を持つ記事は除外される。"""
        since = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)
        old = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)
        entries = [
            {
                "title": "Old Article",
                "link": "https://example.com/old",
                "published_parsed": self._time_tuple(old),
                "updated_parsed": None,
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(len(result), 0)

    def test_article_without_date_is_excluded(self):
        """日付のない記事は新鮮さを確認できないため除外される（古い情報の混入防止）。"""
        since = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)
        entries = [
            {
                "title": "No Date Article",
                "link": "https://example.com/nodate",
                "published_parsed": None,
                "updated_parsed": None,
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(len(result), 0, "日付のない記事は除外されるべき")

    def test_article_older_than_max_age_days_is_excluded(self):
        """MAX_ARTICLE_AGE_DAYS より古い記事は since 以降であっても除外される。"""
        # since を過去にして、MAX_ARTICLE_AGE_DAYS を超える日付を持つ記事をテスト
        since = datetime.now(timezone.utc) - timedelta(days=sc.MAX_ARTICLE_AGE_DAYS + 10)
        very_old = datetime.now(timezone.utc) - timedelta(days=sc.MAX_ARTICLE_AGE_DAYS + 1)
        entries = [
            {
                "title": "Very Old Article",
                "link": "https://example.com/veryold",
                "published_parsed": self._time_tuple(very_old),
                "updated_parsed": None,
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(len(result), 0, f"MAX_ARTICLE_AGE_DAYS ({sc.MAX_ARTICLE_AGE_DAYS}) より古い記事は除外されるべき")

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
            }
        ]
        result = self._run(entries, since)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Fresh Article")

    def test_max_article_age_days_constant_is_30(self):
        """MAX_ARTICLE_AGE_DAYS は 30 日に設定されている。"""
        self.assertEqual(sc.MAX_ARTICLE_AGE_DAYS, 30)


class TestVerifyContentSmallchat(unittest.TestCase):
    """verify_content() の検証プロセスのテスト"""

    def test_valid_article_unchanged(self):
        """正しい形式の記事は変更されない。"""
        md = (
            "## 1. Microsoft\n\n"
            "### Windows 11 の新機能\n\n"
            "**要約**: テスト要約\n\n"
            "**影響**: テスト影響\n\n"
            "**リンク**: [Windows 11](https://example.com/windows)\n"
        )
        result = sc.verify_content(md)
        self.assertEqual(result.strip(), md.strip())

    def test_heading_hyperlink_is_unlinked(self):
        """### [タイトル](URL) 形式の見出しからリンクが除去される。"""
        md = (
            "## 1. Microsoft\n\n"
            "### [Surface Pro Update](https://example.com/surface)\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [Surface Pro Update](https://example.com/surface)\n"
        )
        result = sc.verify_content(md)
        self.assertIn("### Surface Pro Update", result)
        self.assertNotIn("### [Surface Pro Update](https://", result)

    def test_heading_with_brackets_not_hyperlinked_is_preserved(self):
        """角括弧を含むが URL がない見出しは変更されない。"""
        md = (
            "## 1. Microsoft\n\n"
            "### [In preview] New Feature\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n"
        )
        result = sc.verify_content(md)
        self.assertIn("### [In preview] New Feature", result)

    def test_missing_summary_detected(self):
        """**要約** が欠落しているトピックが検出ログに出力される。"""
        md = (
            "## 1. Microsoft\n\n"
            "### トピックA\n\n"
            "内容のみ\n\n"
            "**リンク**: [タイトル](https://example.com)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = sc.verify_content(md)
        self.assertIsInstance(result, str)
        self.assertIn("要約なし:", mock_out.getvalue())

    def test_missing_reference_link_detected(self):
        """**リンク** が欠落しているトピックが検出ログに出力される。"""
        md = (
            "## 1. Microsoft\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = sc.verify_content(md)
        self.assertIsInstance(result, str)
        self.assertIn("リンクなし:", mock_out.getvalue())

    def test_malformed_reference_link_detected(self):
        """**リンク** が [text](URL) 形式でないトピックが検出ログに出力される。"""
        md = (
            "## 2. AI\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: https://example.com/bare\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = sc.verify_content(md)
        self.assertIsInstance(result, str)
        self.assertIn("リンク形式不正:", mock_out.getvalue())

    def test_closing_sentence_removed(self):
        """セクション末尾の締め文が除去される。"""
        md = (
            "## 1. Microsoft\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**影響**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n\n"
            "以上がMicrosoftの最新ニュースです。\n\n"
            "## 2. AI\n"
        )
        result = sc.verify_content(md)
        self.assertNotIn("以上がMicrosoft", result)

    def test_no_info_section_skipped(self):
        """「情報なし」メッセージのセクションは検証をスキップする。"""
        md = (
            "## 1. Microsoft\n\n"
            "現在の対象期間に該当する情報はありません。\n"
        )
        result = sc.verify_content(md)
        self.assertIn("現在の対象期間に該当する情報はありません。", result)

    def test_consecutive_separators_cleaned(self):
        """連続する --- セパレータが整理される。"""
        md = (
            "## 1. Microsoft\n\n"
            "### トピックA\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n\n"
            "---\n\n"
            "---\n\n"
            "### トピックB\n\n"
            "**要約**: テスト2\n\n"
            "**リンク**: [タイトル2](https://example.com/2)\n"
        )
        result = sc.verify_content(md)
        self.assertNotIn("---\n\n---", result)

    def test_empty_section_detected(self):
        """トピックが存在しない空セクションが検出される。"""
        md = (
            "## 1. Microsoft\n\n"
            "## 2. AI\n\n"
            "### AI ニュース\n\n"
            "**要約**: テスト\n\n"
            "**リンク**: [タイトル](https://example.com)\n"
        )
        # 空セクション（Microsoft）が検出されるが例外は出ない
        result = sc.verify_content(md)
        self.assertIsInstance(result, str)


class TestSourceUrlTrackerDelegationInSmallchat(unittest.TestCase):
    """generate_smallchat.py が SourceUrlTracker に委譲することの確認テスト

    ロジックの詳細テストは test_article_generator_shared.py で一元管理する。
    """

    def test_collect_source_urls_is_tracker_method(self):
        """_collect_source_urls は SourceUrlTracker.collect_source_urls に委譲する。"""
        from article_generator_shared import SourceUrlTracker
        self.assertIs(sc._collect_source_urls, SourceUrlTracker.collect_source_urls)

    def test_log_unsourced_is_tracker_method(self):
        """_log_unsourced_reference_links は SourceUrlTracker.log_unsourced_reference_links に委譲する。"""
        from article_generator_shared import SourceUrlTracker
        self.assertIs(sc._log_unsourced_reference_links, SourceUrlTracker.log_unsourced_reference_links)

    def test_collect_source_urls_works_via_alias(self):
        """エイリアス経由でも正しく URL を収集できる（統合確認）。"""
        data = [{"url": "https://blogs.microsoft.com/post"}]
        result = sc._collect_source_urls(data)
        self.assertIn("https://blogs.microsoft.com/post", result)

    def test_log_unsourced_works_via_alias(self):
        """エイリアス経由でも正しくログ出力できる（統合確認）。"""
        article = "### A\n\n**リンク**: [A](https://sourced.example.com)\n"
        source_urls = frozenset({"https://sourced.example.com"})
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            sc._log_unsourced_reference_links(article, source_urls)
        self.assertIn("一致", mock_out.getvalue())


if __name__ == "__main__":
    unittest.main()
