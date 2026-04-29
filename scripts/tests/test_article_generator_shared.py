"""
article_generator_shared.py のユーティリティテスト

generate_daily_update.py と generate_smallchat.py の両ワークフローで
共有されるクラス・関数の挙動を一元的にテストする。
"""

import io
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# スクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from article_generator_shared import SourceUrlTracker


class TestSourceUrlTrackerCollect(unittest.TestCase):
    """SourceUrlTracker.collect_source_urls() のテスト"""

    def test_collects_urls_from_single_list(self):
        """単一の list[dict] から URL を収集する。"""
        data = [
            {"title": "記事A", "url": "https://example.com/a"},
            {"title": "記事B", "url": "https://example.com/b"},
        ]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertIn("https://example.com/a", result)
        self.assertIn("https://example.com/b", result)

    def test_collects_event_urls_from_list(self):
        """event_url キーを持つ dict からも URL を収集する（connpass イベント対応）。"""
        events = [
            {"title": "イベントA", "event_url": "https://connpass.com/event/123/"},
        ]
        result = SourceUrlTracker.collect_source_urls(events)
        self.assertIn("https://connpass.com/event/123/", result)

    def test_url_takes_priority_over_event_url(self):
        """url と event_url の両方があれば url が使われる。"""
        data = [{"url": "https://a.example.com", "event_url": "https://b.example.com"}]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertIn("https://a.example.com", result)

    def test_collects_urls_from_multiple_lists(self):
        """複数の list を受け取り、すべての URL を収集する。"""
        list1 = [{"url": "https://example.com/1"}]
        list2 = [{"url": "https://example.com/2"}]
        list3 = [{"url": "https://example.com/3"}]
        result = SourceUrlTracker.collect_source_urls(list1, list2, list3)
        self.assertIn("https://example.com/1", result)
        self.assertIn("https://example.com/2", result)
        self.assertIn("https://example.com/3", result)
        self.assertEqual(len(result), 3)

    def test_empty_inputs_return_empty_frozenset(self):
        """空リストのみ渡した場合、空の frozenset を返す。"""
        result = SourceUrlTracker.collect_source_urls([], [])
        self.assertIsInstance(result, frozenset)
        self.assertEqual(len(result), 0)

    def test_no_arguments_returns_empty_frozenset(self):
        """引数なしの場合、空の frozenset を返す。"""
        result = SourceUrlTracker.collect_source_urls()
        self.assertIsInstance(result, frozenset)
        self.assertEqual(len(result), 0)

    def test_skips_items_without_url(self):
        """url・event_url キーがない dict は無視される。"""
        data = [
            {"title": "URLなし"},
            {"title": "URLあり", "url": "https://example.com/valid"},
        ]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertEqual(len(result), 1)
        self.assertIn("https://example.com/valid", result)

    def test_skips_empty_url_strings(self):
        """空文字列の url は無視される。"""
        data = [{"url": ""}, {"url": "https://example.com/valid"}]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertEqual(len(result), 1)

    def test_returns_frozenset(self):
        """戻り値は frozenset である。"""
        result = SourceUrlTracker.collect_source_urls([{"url": "https://example.com"}])
        self.assertIsInstance(result, frozenset)

    def test_deduplicates_same_url_across_lists(self):
        """複数リストに同じ URL が存在しても重複なし。"""
        list1 = [{"url": "https://example.com/same"}]
        list2 = [{"url": "https://example.com/same"}]
        result = SourceUrlTracker.collect_source_urls(list1, list2)
        self.assertEqual(len(result), 1)

    def test_skips_non_dict_items(self):
        """dict でない要素はスキップされる。"""
        data = ["string", 42, {"url": "https://example.com/valid"}]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertIn("https://example.com/valid", result)

    def test_can_be_called_as_static_method(self):
        """静的メソッドとしてインスタンスなしで呼べる。"""
        result = SourceUrlTracker.collect_source_urls([{"url": "https://example.com/x"}])
        self.assertIn("https://example.com/x", result)

    def test_can_be_called_on_instance(self):
        """インスタンスメソッドとしても呼べる。"""
        tracker = SourceUrlTracker()
        result = tracker.collect_source_urls([{"url": "https://example.com/y"}])
        self.assertIn("https://example.com/y", result)

    def test_normalizes_url_with_utm_query_params(self):
        """utm_* トラッキングパラメータ付き URL は正規化時にパラメータが除去される。"""
        data = [{"url": "https://example.com/article?utm_source=twitter&utm_medium=social"}]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertIn("https://example.com/article", result)
        self.assertNotIn("https://example.com/article?utm_source=twitter&utm_medium=social", result)

    def test_normalizes_url_with_fragment(self):
        """フラグメント付き URL は正規化（フラグメント除去）して格納される。"""
        data = [{"url": "https://example.com/article#section1"}]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertIn("https://example.com/article", result)
        self.assertNotIn("https://example.com/article#section1", result)

    def test_deduplicates_urls_differing_only_in_utm_params(self):
        """utm_* トラッキングパラメータのみ異なる同一パスの URL は正規化後に重複除去される。"""
        data = [
            {"url": "https://example.com/article?utm_source=twitter"},
            {"url": "https://example.com/article?utm_source=facebook"},
            {"url": "https://example.com/article"},
        ]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertEqual(len(result), 1)
        self.assertIn("https://example.com/article", result)

    def test_preserves_content_identifier_query_params(self):
        """id= などのコンテンツ識別パラメータは正規化後も保持される。

        Azure アップデートの URL（?id=NNNN）のように、クエリパラメータが
        記事の識別子として機能する場合は除去しない。
        異なる id を持つ URL は別々のエントリとして収集される。
        """
        data = [
            {"url": "https://azure.microsoft.com/updates?id=560904"},
            {"url": "https://azure.microsoft.com/updates?id=560987"},
        ]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertEqual(len(result), 2)
        self.assertIn("https://azure.microsoft.com/updates?id=560904", result)
        self.assertIn("https://azure.microsoft.com/updates?id=560987", result)

    def test_strips_utm_but_preserves_id_param(self):
        """utm_* は除去するが id= は保持する（複合クエリパラメータ）。"""
        data = [{"url": "https://azure.microsoft.com/updates?id=560904&utm_source=rss"}]
        result = SourceUrlTracker.collect_source_urls(data)
        self.assertEqual(result, frozenset({"https://azure.microsoft.com/updates?id=560904"}))

class TestSourceUrlTrackerLog(unittest.TestCase):
    """SourceUrlTracker.log_unsourced_reference_links() のテスト"""

    def _make_article(self, url: str) -> str:
        return (
            "## 1. テストセクション\n\n"
            f"### トピックA\n\n**要約**: テスト\n\n**リンク**: [タイトルA]({url})\n"
        )

    def test_sourced_url_logs_no_warning(self):
        """リンク URL がソースに含まれる場合、ソース外の警告ログが出ない。"""
        url = "https://azure.microsoft.com/blog/update"
        source_urls = frozenset({url})
        article = self._make_article(url)

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, source_urls)

        self.assertNotIn("ソース外リンク:", mock_out.getvalue())
        self.assertIn("ソースデータと一致", mock_out.getvalue())

    def test_unsourced_url_logs_warning(self):
        """リンク URL がソースに含まれない場合、警告ログが出力される。"""
        url = "https://hallucinated.example.com/article"
        source_urls = frozenset()
        article = self._make_article(url)

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, source_urls)

        self.assertIn("ソース外リンク:", mock_out.getvalue())

    def test_unsourced_url_log_shows_count(self):
        """ソース外 URL の件数がログに含まれる。"""
        article = (
            "### A\n\n**リンク**: [A](https://bad1.example.com)\n\n"
            "### B\n\n**リンク**: [B](https://bad2.example.com)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, frozenset())

        self.assertIn("2 件", mock_out.getvalue())

    def test_returns_none(self):
        """戻り値は None（記事を変更しない）。"""
        article = self._make_article("https://example.com/a")
        result = SourceUrlTracker.log_unsourced_reference_links(article, frozenset())
        self.assertIsNone(result)

    def test_no_reference_links_logs_all_match(self):
        """リンクがない場合、「一致」メッセージが出力される。"""
        article = "## テスト\n\n内容のみ\n"
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, frozenset())

        self.assertIn("ソースデータと一致", mock_out.getvalue())

    def test_unsourced_url_log_truncated_to_five(self):
        """ソース外 URL が 5 件を超えても最大 5 件のみログ出力する。"""
        article_lines = []
        for i in range(7):
            article_lines.append(f"### Topic {i}\n\n**リンク**: [T{i}](https://bad{i}.example.com)")
        article = "\n\n".join(article_lines)

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, frozenset())

        output_lines = [l for l in mock_out.getvalue().splitlines() if "ℹ" in l]
        self.assertLessEqual(len(output_lines), 5)

    def test_can_be_called_on_instance(self):
        """インスタンスメソッドとしても呼べる。"""
        tracker = SourceUrlTracker()
        article = self._make_article("https://example.com/x")
        # 例外が出ないことを確認
        with patch('sys.stdout', new_callable=io.StringIO):
            tracker.log_unsourced_reference_links(article, frozenset())

    def test_url_with_query_params_matches_normalized_source(self):
        """リンクにクエリパラメータがあっても、正規化後にソースと一致すれば警告しない。"""
        base_url = "https://azure.microsoft.com/blog/update"
        source_urls = frozenset({base_url})
        article = self._make_article(f"{base_url}?utm_source=twitter&utm_medium=social")

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, source_urls)

        self.assertNotIn("ソース外リンク:", mock_out.getvalue())
        self.assertIn("ソースデータと一致", mock_out.getvalue())

    def test_url_with_fragment_matches_normalized_source(self):
        """リンクにフラグメントがあっても、正規化後にソースと一致すれば警告しない。"""
        base_url = "https://azure.microsoft.com/blog/update"
        source_urls = frozenset({base_url})
        article = self._make_article(f"{base_url}#section2")

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, source_urls)

        self.assertNotIn("ソース外リンク:", mock_out.getvalue())
        self.assertIn("ソースデータと一致", mock_out.getvalue())


class TestSourceUrlTrackerDelegationDaily(unittest.TestCase):
    """generate_daily_update.py からの SourceUrlTracker 委譲テスト"""

    def test_daily_update_uses_shared_collect_source_urls(self):
        """generate_daily_update の _collect_source_urls は SourceUrlTracker に委譲する。"""
        import generate_daily_update as du
        self.assertIs(du._collect_source_urls, SourceUrlTracker.collect_source_urls)

    def test_daily_update_uses_shared_log_unsourced(self):
        """generate_daily_update の _log_unsourced_reference_links は SourceUrlTracker に委譲する。"""
        import generate_daily_update as du
        self.assertIs(du._log_unsourced_reference_links, SourceUrlTracker.log_unsourced_reference_links)


class TestSourceUrlTrackerDelegationSmallchat(unittest.TestCase):
    """generate_smallchat.py からの SourceUrlTracker 委譲テスト"""

    def test_smallchat_uses_shared_collect_source_urls(self):
        """generate_smallchat の _collect_source_urls は SourceUrlTracker に委譲する。"""
        import generate_smallchat as sc
        self.assertIs(sc._collect_source_urls, SourceUrlTracker.collect_source_urls)

    def test_smallchat_uses_shared_log_unsourced(self):
        """generate_smallchat の _log_unsourced_reference_links は SourceUrlTracker に委譲する。"""
        import generate_smallchat as sc
        self.assertIs(sc._log_unsourced_reference_links, SourceUrlTracker.log_unsourced_reference_links)


class TestSharedFunctionsDelegationDaily(unittest.TestCase):
    """generate_daily_update.py が共有関数に委譲しているかを検証するテスト"""

    def setUp(self):
        import generate_daily_update as du
        self.du = du

    def test_validate_links_is_shared(self):
        """generate_daily_update の validate_links は共有モジュールの実装を使用する。"""
        from article_generator_shared import validate_links
        self.assertIs(self.du.validate_links, validate_links)

    def test_verify_content_is_shared(self):
        """generate_daily_update の verify_content は共有モジュールの実装を使用する。"""
        from article_generator_shared import verify_content
        self.assertIs(self.du.verify_content, verify_content)

    def test_format_bare_reference_links_is_shared(self):
        """generate_daily_update の _format_bare_reference_links は共有モジュールの実装を使用する。"""
        from article_generator_shared import _format_bare_reference_links
        self.assertIs(self.du._format_bare_reference_links, _format_bare_reference_links)

    def test_validate_url_is_shared(self):
        """generate_daily_update の _validate_url は共有モジュールの実装を使用する。"""
        from article_generator_shared import _validate_url
        self.assertIs(self.du._validate_url, _validate_url)

    def test_search_alternative_url_is_shared(self):
        """generate_daily_update の _search_alternative_url は共有モジュールの実装を使用する。"""
        from article_generator_shared import _search_alternative_url
        self.assertIs(self.du._search_alternative_url, _search_alternative_url)

    def test_resolve_google_news_url_is_shared(self):
        """generate_daily_update の _resolve_google_news_url は共有モジュールの実装を使用する。"""
        from article_generator_shared import _resolve_google_news_url
        self.assertIs(self.du._resolve_google_news_url, _resolve_google_news_url)

    def test_build_section_prompt_is_shared(self):
        """generate_daily_update の _build_section_prompt は共有モジュールの実装を使用する。"""
        from article_generator_shared import _build_section_prompt
        self.assertIs(self.du._build_section_prompt, _build_section_prompt)

    def test_http_headers_is_shared(self):
        """generate_daily_update の HTTP_HEADERS は共有モジュールの定数を使用する。"""
        from article_generator_shared import HTTP_HEADERS
        self.assertIs(self.du.HTTP_HEADERS, HTTP_HEADERS)

    def test_general_news_feeds_is_shared(self):
        """generate_daily_update の GENERAL_NEWS_FEEDS は共有モジュールの定数を使用する。"""
        from article_generator_shared import GENERAL_NEWS_FEEDS
        self.assertIs(self.du.GENERAL_NEWS_FEEDS, GENERAL_NEWS_FEEDS)


class TestSharedFunctionsDelegationSmallchat(unittest.TestCase):
    """generate_smallchat.py が共有関数に委譲しているかを検証するテスト"""

    def setUp(self):
        import generate_smallchat as sc
        self.sc = sc

    def test_validate_links_is_shared(self):
        """generate_smallchat の validate_links は共有モジュールの実装を使用する。"""
        from article_generator_shared import validate_links
        self.assertIs(self.sc.validate_links, validate_links)

    def test_verify_content_is_shared(self):
        """generate_smallchat の verify_content は共有モジュールの実装を使用する。"""
        from article_generator_shared import verify_content
        self.assertIs(self.sc.verify_content, verify_content)

    def test_format_bare_reference_links_is_shared(self):
        """generate_smallchat の _format_bare_reference_links は共有モジュールの実装を使用する。"""
        from article_generator_shared import _format_bare_reference_links
        self.assertIs(self.sc._format_bare_reference_links, _format_bare_reference_links)

    def test_validate_url_is_shared(self):
        """generate_smallchat の _validate_url は共有モジュールの実装を使用する。"""
        from article_generator_shared import _validate_url
        self.assertIs(self.sc._validate_url, _validate_url)

    def test_search_alternative_url_is_shared(self):
        """generate_smallchat の _search_alternative_url は共有モジュールの実装を使用する。"""
        from article_generator_shared import _search_alternative_url
        self.assertIs(self.sc._search_alternative_url, _search_alternative_url)

    def test_resolve_google_news_url_is_shared(self):
        """generate_smallchat の _resolve_google_news_url は共有モジュールの実装を使用する。"""
        from article_generator_shared import _resolve_google_news_url
        self.assertIs(self.sc._resolve_google_news_url, _resolve_google_news_url)

    def test_build_section_prompt_is_shared(self):
        """generate_smallchat の _build_section_prompt は共有モジュールの実装を使用する。"""
        from article_generator_shared import _build_section_prompt
        self.assertIs(self.sc._build_section_prompt, _build_section_prompt)

    def test_http_headers_is_shared(self):
        """generate_smallchat の HTTP_HEADERS は共有モジュールの定数を使用する。"""
        from article_generator_shared import HTTP_HEADERS
        self.assertIs(self.sc.HTTP_HEADERS, HTTP_HEADERS)

    def test_general_news_feeds_is_shared(self):
        """generate_smallchat の GENERAL_NEWS_FEEDS は共有モジュールの定数を使用する。"""
        from article_generator_shared import GENERAL_NEWS_FEEDS
        self.assertIs(self.sc.GENERAL_NEWS_FEEDS, GENERAL_NEWS_FEEDS)


class TestSharedFunctionsModule(unittest.TestCase):
    """article_generator_shared の新規共有関数の基本動作テスト"""

    def test_format_bare_reference_links_bare_url(self):
        """裸の URL が直近の ### 見出しをラベルにしたリンクへ変換される。"""
        from article_generator_shared import _format_bare_reference_links
        md = "### Azure Monitor\n\n**リンク**: https://docs.microsoft.com/azure/\n"
        result = _format_bare_reference_links(md)
        self.assertIn("[Azure Monitor](https://docs.microsoft.com/azure/)", result)
        self.assertNotIn("**リンク**: https://", result)

    def test_verify_content_community_section_is_skipped(self):
        """コミュニティセクションの📅・📝見出しは要約・リンクチェックを省略する。"""
        import io
        from article_generator_shared import verify_content
        md = (
            "## 5. コミュニティイベント情報\n\n"
            "### 📅 東京勉強会\n\n"
            "- 日時: 2026-04-20\n\n"
            "---\n\n"
            "### 📝 参加レポート・イベント宣伝まとめ\n\n"
            "内容のみ（要約・リンクなし）\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = verify_content(md)
        # コミュニティ箇条書きは要約・リンクなし警告が出ないこと
        output = mock_out.getvalue()
        self.assertNotIn("要約なし", output)
        self.assertNotIn("リンクなし", output)

    def test_http_headers_user_agent(self):
        """HTTP_HEADERS に User-Agent が含まれる。"""
        from article_generator_shared import HTTP_HEADERS
        self.assertIn("User-Agent", HTTP_HEADERS)
        self.assertIn("daily-updates-bot", HTTP_HEADERS["User-Agent"])

    def test_general_news_feeds_is_list(self):
        """GENERAL_NEWS_FEEDS はリスト形式で定義されている。"""
        from article_generator_shared import GENERAL_NEWS_FEEDS
        self.assertIsInstance(GENERAL_NEWS_FEEDS, list)
        self.assertGreater(len(GENERAL_NEWS_FEEDS), 0)
        for feed in GENERAL_NEWS_FEEDS:
            self.assertIn("name", feed)
            self.assertIn("url", feed)

    def test_fetch_category_deduplicates_urls(self):
        """fetch_category は重複 URL を除外する。"""
        from unittest.mock import patch as mpatch, MagicMock
        from article_generator_shared import fetch_category

        duplicate_item = {"url": "https://example.com/same", "title": "記事"}
        feeds = {"test_cat": [
            {"name": "Feed A", "url": "https://feed-a.example.com/rss"},
            {"name": "Feed B", "url": "https://feed-b.example.com/rss"},
        ]}

        def fake_fetch_feed(url, since, max_items=10, max_age_days=None):
            return [dict(duplicate_item)]

        with mpatch.object(
            sys.modules["article_generator_shared"], "_fetch_feed",
            side_effect=fake_fetch_feed
        ):
            result = fetch_category(feeds, "test_cat", object())

        urls = [r["url"] for r in result]
        self.assertEqual(len(set(urls)), len(urls), "重複 URL が含まれている")
        self.assertEqual(len(result), 1)

    def test_generate_section_empty_list_returns_no_info(self):
        """generate_section は空データの場合 LLM を呼ばずに「ありません」を返す。"""
        from article_generator_shared import generate_section
        client = MagicMock()
        section = {"key": "test", "header": "## テスト", "system": "sys", "instruction": "inst"}
        result = generate_section(client, "gpt-4o", section, [])
        self.assertEqual(client.chat.completions.create.call_count, 0)
        self.assertIn("## テスト", result)
        self.assertIn("ありません", result)

    def test_generate_section_respects_temperature_param(self):
        """generate_section は temperature パラメータを API 呼び出しに渡す。"""
        from article_generator_shared import generate_section
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = "出力"
        client.chat.completions.create.return_value.choices = [choice]
        section = {"key": "test", "header": "## T", "system": "sys", "instruction": "inst", "data_label": "データ"}
        generate_section(client, "gpt-4o", section, [{"title": "記事"}], temperature=0.7)
        call_kwargs = client.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs["temperature"], 0.7)

    def test_build_section_prompt_handles_dict_data(self):
        """_build_section_prompt は dict 型データを各キーをラベルに展開する。"""
        from article_generator_shared import _build_section_prompt
        section = {"instruction": "指示", "data_label": "デフォルト"}
        data = {"ラベルA": [{"title": "記事A"}], "ラベルB": [{"title": "記事B"}]}
        prompt = _build_section_prompt(section, data)
        self.assertIn("ラベルA", prompt)
        self.assertIn("ラベルB", prompt)
        self.assertIn("記事A", prompt)
        self.assertIn("記事B", prompt)

    def test_build_section_prompt_handles_list_data(self):
        """_build_section_prompt は list 型データを data_label でラベル付けする。"""
        from article_generator_shared import _build_section_prompt
        section = {"instruction": "指示", "data_label": "記事データ"}
        data = [{"title": "記事A"}]
        prompt = _build_section_prompt(section, data)
        self.assertIn("記事データ", prompt)
        self.assertIn("記事A", prompt)


class TestValidateUrlSoftFail(unittest.TestCase):
    """_validate_url() のソフトフェイル動作テスト"""

    def test_connection_error_returns_true(self):
        """接続エラー時はソフトフェイル（True, 検証スキップ）を返す。"""
        import article_generator_shared as ags
        with patch.object(ags.requests, "head", side_effect=ags.requests.ConnectionError("timeout")):
            ok, reason = ags._validate_url("https://example.com/article")
        self.assertTrue(ok, "接続エラー時は有効（True）を返すべき")
        self.assertIn("スキップ", reason)

    def test_timeout_returns_true(self):
        """タイムアウト時はソフトフェイル（True, 検証スキップ）を返す。"""
        import article_generator_shared as ags
        with patch.object(ags.requests, "head", side_effect=ags.requests.Timeout("timed out")):
            ok, reason = ags._validate_url("https://example.com/article")
        self.assertTrue(ok, "タイムアウト時は有効（True）を返すべき")
        self.assertIn("スキップ", reason)

    def test_http_404_returns_false(self):
        """HTTP 404 は依然として無効（False）を返す。"""
        import article_generator_shared as ags
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.headers.get.return_value = "text/html"
        mock_resp.url = "https://example.com/article"
        with patch.object(ags.requests, "head", return_value=mock_resp):
            ok, reason = ags._validate_url("https://example.com/article")
        self.assertFalse(ok, "HTTP 404 は無効（False）を返すべき")
        self.assertIn("404", reason)

    def test_ssl_error_returns_false(self):
        """SSL エラー等の恒久的エラーは無効（False）を返す。"""
        import article_generator_shared as ags
        with patch.object(ags.requests, "head", side_effect=ags.requests.exceptions.SSLError("ssl error")):
            ok, reason = ags._validate_url("https://example.com/article")
        self.assertFalse(ok, "SSL エラーは無効（False）を返すべき")
        self.assertIn("接続エラー", reason)

    def test_uses_shorter_timeout(self):
        """_validate_url は短縮されたタイムアウト（5 秒）を使用する。"""
        import article_generator_shared as ags
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers.get.return_value = "text/html"
        mock_resp.url = "https://example.com/article"
        with patch.object(ags.requests, "head", return_value=mock_resp) as mock_head:
            ags._validate_url("https://example.com/article")
        _, kwargs = mock_head.call_args
        self.assertEqual(kwargs.get("timeout"), 5, "タイムアウトは 5 秒であるべき")


class TestSearchAlternativeUrlSoftFail(unittest.TestCase):
    """_search_alternative_url() のソフトフェイル動作テスト"""

    def test_network_error_returns_sentinel(self):
        """ネットワーク障害時は _SEARCH_UNAVAILABLE センチネルを返す。"""
        import article_generator_shared as ags
        with patch.object(ags.requests, "get", side_effect=ags.requests.ConnectionError("no connection")):
            result = ags._search_alternative_url("検索クエリ")
        self.assertIs(result, ags._SEARCH_UNAVAILABLE, "ネットワーク障害時は _SEARCH_UNAVAILABLE を返すべき")

    def test_timeout_returns_sentinel(self):
        """タイムアウト時は _SEARCH_UNAVAILABLE センチネルを返す。"""
        import article_generator_shared as ags
        with patch.object(ags.requests, "get", side_effect=ags.requests.Timeout("timed out")):
            result = ags._search_alternative_url("検索クエリ")
        self.assertIs(result, ags._SEARCH_UNAVAILABLE, "タイムアウト時は _SEARCH_UNAVAILABLE を返すべき")

    def test_5xx_status_returns_sentinel(self):
        """HTTP 5xx レスポンスは _SEARCH_UNAVAILABLE を返す。"""
        import article_generator_shared as ags
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch.object(ags.requests, "get", return_value=mock_resp):
            result = ags._search_alternative_url("検索クエリ")
        self.assertIs(result, ags._SEARCH_UNAVAILABLE, "HTTP 5xx は _SEARCH_UNAVAILABLE を返すべき")

    def test_4xx_status_returns_none(self):
        """HTTP 4xx レスポンスは None（結果なし）を返す。"""
        import article_generator_shared as ags
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch.object(ags.requests, "get", return_value=mock_resp):
            result = ags._search_alternative_url("検索クエリ")
        self.assertIsNone(result, "HTTP 4xx は None を返すべき")

    def test_uses_shorter_timeout(self):
        """_search_alternative_url は短縮されたタイムアウト（10 秒）を使用する。"""
        import article_generator_shared as ags
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b""
        with patch.object(ags.requests, "get", return_value=mock_resp) as mock_get, \
             patch.object(ags, "feedparser") as mock_feedparser:
            mock_feedparser.parse.return_value.entries = []
            ags._search_alternative_url("検索クエリ")
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs.get("timeout"), 10, "タイムアウトは 10 秒であるべき")


class TestValidateLinksSoftFail(unittest.TestCase):
    """validate_links() のソフトフェイル動作テスト"""

    def _make_article(self, url: str) -> str:
        return (
            "## 1. テスト\n\n"
            f"### トピック\n\n"
            f"**要約**: 内容\n\n"
            f"**リンク**: [タイトル]({url})\n"
        )

    def test_search_unavailable_keeps_original_content(self):
        """検索サービス障害時はトピックを除去せず元のコンテンツを保持する。"""
        import article_generator_shared as ags
        url = "https://bad.example.com/article"
        markdown = self._make_article(url)

        with (patch.object(ags, "_validate_url", return_value=(False, "HTTP 404")),
              patch.object(ags, "_search_alternative_url", return_value=ags._SEARCH_UNAVAILABLE)):
            result = ags.validate_links(markdown)

        # トピックが除去されていないこと
        self.assertIn("トピック", result)
        self.assertIn(url, result)

    def test_search_unavailable_does_not_add_to_unfixable(self):
        """検索サービス障害時はトピックを除去せず、複数 URL でも保持する。"""
        import article_generator_shared as ags
        markdown = (
            "## 1. テスト\n\n"
            "### トピック A\n\n"
            "**要約**: 内容 A\n\n"
            "**リンク**: [A](https://bad-a.example.com)\n\n"
            "---\n\n"
            "### トピック B\n\n"
            "**要約**: 内容 B\n\n"
            "**リンク**: [B](https://bad-b.example.com)\n"
        )

        with (patch.object(ags, "_validate_url", return_value=(False, "HTTP 404")),
              patch.object(ags, "_search_alternative_url", return_value=ags._SEARCH_UNAVAILABLE)):
            result = ags.validate_links(markdown)

        # どちらのトピックも除去されていないこと
        self.assertIn("トピック A", result)
        self.assertIn("トピック B", result)

    def test_search_none_removes_topic(self):
        """検索結果なし（None）の場合は従来通りトピックを除去する。"""
        import article_generator_shared as ags
        url = "https://bad.example.com/article"
        markdown = self._make_article(url)

        with (patch.object(ags, "_validate_url", return_value=(False, "HTTP 404")),
              patch.object(ags, "_search_alternative_url", return_value=None)):
            result = ags.validate_links(markdown)

        # トピックが除去されていること
        self.assertNotIn("トピック", result)

    def test_connection_error_skips_validation(self):
        """接続エラーのある URL は無効とみなされず、代替検索を呼ばない。"""
        import article_generator_shared as ags
        url = "https://timeout.example.com/article"
        markdown = self._make_article(url)

        with (patch.object(ags, "_validate_url", return_value=(True, "検証スキップ (ConnectionError)")),
              patch.object(ags, "_search_alternative_url") as mock_search):
            result = ags.validate_links(markdown)

        # 代替検索が呼ばれないこと（接続エラーは有効とみなすため）
        mock_search.assert_not_called()
        # コンテンツが保持されていること
        self.assertIn("トピック", result)
        self.assertIn(url, result)



class TestGenerateSectionRetry(unittest.TestCase):
    """generate_section() の指数バックオフリトライ動作テスト"""

    def _make_section(self):
        return {
            "key": "test",
            "header": "## テスト",
            "system": "sys",
            "instruction": "inst",
            "data_label": "データ",
        }

    def _make_client(self, content="出力"):
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        client.chat.completions.create.return_value.choices = [choice]
        return client

    def _make_choice(self, content="成功"):
        choice = MagicMock()
        choice.message.content = content
        return choice

    def test_success_on_first_attempt_no_sleep(self):
        """初回成功時はスリープなしで結果を返す。"""
        import article_generator_shared as ags
        client = self._make_client("出力")
        section = self._make_section()
        with patch("article_generator_shared.time") as mock_time:
            result = ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        self.assertEqual(result, "出力")
        mock_time.sleep.assert_not_called()
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_retries_on_rate_limit_error(self):
        """RateLimitError が発生した場合、リトライして成功する。"""
        import article_generator_shared as ags
        from openai import RateLimitError
        client = MagicMock()
        rate_limit_err = RateLimitError(
            message="rate limit", response=MagicMock(), body={}
        )
        client.chat.completions.create.side_effect = [
            rate_limit_err,
            MagicMock(choices=[self._make_choice()]),
        ]
        section = self._make_section()
        with patch("article_generator_shared.time") as mock_time:
            result = ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        self.assertEqual(result, "成功")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        mock_time.sleep.assert_called_once_with(ags._LLM_RETRY_BASE_WAIT)

    def test_retries_on_api_connection_error(self):
        """APIConnectionError が発生した場合、リトライして成功する。"""
        import article_generator_shared as ags
        from openai import APIConnectionError
        client = MagicMock()
        conn_err = APIConnectionError(request=MagicMock())
        client.chat.completions.create.side_effect = [
            conn_err,
            MagicMock(choices=[self._make_choice()]),
        ]
        section = self._make_section()
        with patch("article_generator_shared.time") as mock_time:
            result = ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        self.assertEqual(result, "成功")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        mock_time.sleep.assert_called_once()

    def test_retries_on_internal_server_error(self):
        """InternalServerError が発生した場合、リトライして成功する。"""
        import article_generator_shared as ags
        from openai import InternalServerError
        client = MagicMock()
        server_err = InternalServerError(
            message="internal server error", response=MagicMock(), body={}
        )
        client.chat.completions.create.side_effect = [
            server_err,
            MagicMock(choices=[self._make_choice()]),
        ]
        section = self._make_section()
        with patch("article_generator_shared.time") as mock_time:
            result = ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        self.assertEqual(result, "成功")
        mock_time.sleep.assert_called_once()

    def test_raises_after_max_retries_exhausted(self):
        """全リトライが失敗した場合、最後のエラーを raise する。"""
        import article_generator_shared as ags
        from openai import RateLimitError
        client = MagicMock()
        rate_limit_err = RateLimitError(
            message="rate limit", response=MagicMock(), body={}
        )
        client.chat.completions.create.side_effect = rate_limit_err
        section = self._make_section()
        with patch("article_generator_shared.time"):
            with self.assertRaises(RateLimitError):
                ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        self.assertEqual(client.chat.completions.create.call_count, ags._LLM_MAX_RETRIES)

    def test_exponential_backoff_wait_times(self):
        """リトライのたびに待機時間が指数的に増加する。"""
        import article_generator_shared as ags
        from openai import RateLimitError
        client = MagicMock()
        rate_limit_err = RateLimitError(
            message="rate limit", response=MagicMock(), body={}
        )
        client.chat.completions.create.side_effect = rate_limit_err
        section = self._make_section()
        with patch("article_generator_shared.time") as mock_time:
            with self.assertRaises(RateLimitError):
                ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        expected_waits = [
            ags._LLM_RETRY_BASE_WAIT * (2 ** i)
            for i in range(ags._LLM_MAX_RETRIES - 1)
        ]
        actual_waits = [call.args[0] for call in mock_time.sleep.call_args_list]
        self.assertEqual(actual_waits, expected_waits)

    def test_non_transient_error_not_retried(self):
        """一時的でないエラー（AuthenticationError 等）はリトライせずに即座に raise する。"""
        import article_generator_shared as ags
        from openai import AuthenticationError
        client = MagicMock()
        auth_err = AuthenticationError(
            message="invalid api key", response=MagicMock(), body={}
        )
        client.chat.completions.create.side_effect = auth_err
        section = self._make_section()
        with patch("article_generator_shared.time") as mock_time:
            with self.assertRaises(AuthenticationError):
                ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])
        mock_time.sleep.assert_not_called()
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_max_retries_zero_raises_runtime_error(self):
        """_LLM_MAX_RETRIES が 0 の場合、RuntimeError を発生させる。"""
        import article_generator_shared as ags
        client = MagicMock()
        section = self._make_section()
        with patch.object(ags, "_LLM_MAX_RETRIES", 0):
            with self.assertRaises(RuntimeError, msg="_LLM_MAX_RETRIES must be at least 1."):
                ags.generate_section(client, "gpt-4o", section, [{"title": "記事"}])


class TestReplaceUnsourcedReferenceLinks(unittest.TestCase):
    """SourceUrlTracker.replace_unsourced_reference_links() のテスト"""

    _SOURCE_DATA = [
        {
            "title": "[In preview] Public Preview: Azure Backup for Elastic SAN",
            "url": "https://azure.microsoft.com/updates?id=560904",
        },
        {
            "title": "[Launched] Generally Available: Foundry Toolkit for Visual Studio Code",
            "url": "https://azure.microsoft.com/updates?id=560987",
        },
        {
            "title": "Azure Kubernetes Service latest updates",
            "url": "https://azure.microsoft.com/updates?id=560015",
        },
    ]

    def _make_article(self, heading: str, url: str) -> str:
        return (
            "## 1. Azure アップデート情報\n\n"
            f"### {heading}\n\n"
            "**要約**: テスト内容\n\n"
            "**影響**: テスト影響\n\n"
            f"**リンク**: [{heading}]({url})\n"
        )

    def _source_urls(self) -> frozenset:
        return SourceUrlTracker.collect_source_urls(self._SOURCE_DATA)

    def test_replaces_hallucinated_url_with_source_url(self):
        """LLM が生成した非ソース URL がソースデータの URL に置換される。"""
        article = self._make_article(
            "Public Preview: Azure Backup for Elastic SAN",
            "https://www.softbank.jp/biz/blog/cloud-technology/articles/fake/",
        )
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, self._SOURCE_DATA, self._source_urls()
            )
        self.assertIn("https://azure.microsoft.com/updates?id=560904", result)
        self.assertNotIn("softbank.jp", result)

    def test_preserves_correct_source_url(self):
        """すでにソースデータの URL を使用しているリンクは変更しない。"""
        correct_url = "https://azure.microsoft.com/updates?id=560904"
        article = self._make_article(
            "Public Preview: Azure Backup for Elastic SAN",
            correct_url,
        )
        source_urls = self._source_urls()
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, self._SOURCE_DATA, source_urls
            )
        self.assertIn(correct_url, result)
        self.assertEqual(article, result)

    def test_no_replacement_when_score_too_low(self):
        """ソースデータとの一致スコアが 0.5 未満の場合は置換しない。"""
        article = self._make_article(
            "全く関係ないトピック",
            "https://hallucinated.example.com/unrelated",
        )
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, self._SOURCE_DATA, self._source_urls()
            )
        self.assertIn("hallucinated.example.com", result)

    def test_empty_source_data_returns_article_unchanged(self):
        """ソースデータが空の場合は記事を変更しない。"""
        article = self._make_article(
            "Azure Backup",
            "https://hallucinated.example.com/fake",
        )
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, [], frozenset()
            )
        self.assertEqual(article, result)

    def test_replaces_using_heading_from_topic_block(self):
        """### 見出しのテキストを使って対応するソース URL を特定する。"""
        article = (
            "## 1. Azure\n\n"
            "### Foundry Toolkit for Visual Studio Code\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            "**リンク**: [Foundry Toolkit](https://codezine.jp/fake/article)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, self._SOURCE_DATA, self._source_urls()
            )
        self.assertIn("https://azure.microsoft.com/updates?id=560987", result)
        self.assertNotIn("codezine.jp", result)

    def test_prefix_stripped_for_matching(self):
        """ソースタイトルの [In preview] 等のプレフィックスを除去してマッチングする。"""
        # Source title: "[In preview] Public Preview: Azure Backup for Elastic SAN"
        # Heading: "Public Preview: Azure Backup for Elastic SAN"
        article = (
            "## 1. Azure\n\n"
            "### Public Preview: Azure Backup for Elastic SAN\n\n"
            "**要約**: ...\n\n"
            "**リンク**: [title](https://wrong.example.com/)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, self._SOURCE_DATA, self._source_urls()
            )
        self.assertIn("https://azure.microsoft.com/updates?id=560904", result)

    def test_replaces_using_source_name_label_when_primary_fails(self):
        """リンクラベルがソース名と一致し、1次マッチングが閾値未満でも置換する。

        LLM がソース名をラベルに使い、ソース名から推測した URL（e.g. サブレディット root）を
        生成するケースを想定。2次マッチング（ソース名絞り込み + 閾値 0.3）で正しい URL に置換する。
        """
        source_data = [
            {
                # 見出し "AI Safety Release Concerns and Tech Impact Analysis" との1次スコア:
                # 共通語 {"ai", "safety", "release"} = 3、max(8, 4) = 8 → 0.375 (< 0.5, ≥ 0.3)
                "title": "AI Safety: Release Considerations",
                "url": "https://www.reddit.com/r/artificial/comments/abc123/ai_safety_release/",
                "source": "Reddit Artificial",
            },
            {
                "title": "Azure Kubernetes Service Update",
                "url": "https://azure.microsoft.com/updates?id=123",
                "source": "Azure Blog",
            },
        ]
        article = (
            "## 2. AI\n\n"
            "### AI Safety Release Concerns and Tech Impact Analysis\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            "**リンク**: [Reddit Artificial](https://www.reddit.com/r/artificial/)\n"
        )
        source_urls = SourceUrlTracker.collect_source_urls(source_data)
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, source_data, source_urls
            )
        self.assertIn(
            "https://www.reddit.com/r/artificial/comments/abc123/ai_safety_release/", result
        )
        self.assertNotIn("https://www.reddit.com/r/artificial/)\n", result)

    def test_replaces_azure_url_with_wrong_id(self):
        """LLM が生成した Azure URL の ?id= が異なる場合に正しい URL に置換する。

        Azure アップデートの URL は ?id=NNNN で記事を識別する。以前の実装では
        クエリパラメータを全除去するため異なる ID でも「一致」とみなされていたが、
        修正後は id= を保持するため、誤 ID は「ソース外」と検出され置換される。
        """
        source_data = [
            {
                "title": "Azure Backup for Elastic SAN General Availability",
                "url": "https://azure.microsoft.com/updates?id=560904",
                "source": "Azure Release Communications",
            },
        ]
        article = (
            "## 1. Azure アップデート情報\n\n"
            "### Azure Backup for Elastic SAN General Availability\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            "**リンク**: [Azure Backup for Elastic SAN](https://azure.microsoft.com/updates?id=999999)\n"
        )
        source_urls = SourceUrlTracker.collect_source_urls(source_data)
        with patch('sys.stdout', new_callable=io.StringIO):
            result = SourceUrlTracker.replace_unsourced_reference_links(
                article, source_data, source_urls
            )
        self.assertIn("https://azure.microsoft.com/updates?id=560904", result)
        self.assertNotIn("?id=999999", result)

    def test_daily_update_delegates_to_source_url_tracker(self):
        """generate_daily_update の _replace_unsourced は SourceUrlTracker に委譲する。"""
        import generate_daily_update as du
        self.assertIs(
            du._replace_unsourced_reference_links,
            SourceUrlTracker.replace_unsourced_reference_links,
        )

    def test_smallchat_delegates_to_source_url_tracker(self):
        """generate_smallchat の _replace_unsourced は SourceUrlTracker に委譲する。"""
        import generate_smallchat as sc
        self.assertIs(
            sc._replace_unsourced_reference_links,
            SourceUrlTracker.replace_unsourced_reference_links,
        )


class TestVerifyLinkSourceMatch(unittest.TestCase):
    """SourceUrlTracker.verify_link_source_match() のテスト"""

    def _make_article(self, heading: str, url: str) -> str:
        return (
            "## 1. Azure アップデート情報\n\n"
            f"### {heading}\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            f"**リンク**: [{heading}]({url})\n"
        )

    def test_matching_content_logs_no_warning(self):
        """リンクのソースデータ title がトピック見出しと一致する場合は警告なし。"""
        source_data = [
            {
                "title": "Azure Backup for Elastic SAN General Availability",
                "url": "https://azure.microsoft.com/updates?id=560904",
                "description": "Azure Backup now supports Elastic SAN...",
                "source": "Azure Release Communications",
            },
        ]
        article = self._make_article(
            "Azure Backup for Elastic SAN General Availability",
            "https://azure.microsoft.com/updates?id=560904",
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        self.assertNotIn("低スコア", mock_out.getvalue())
        self.assertIn("問題なし", mock_out.getvalue())
        # 修正不要なので記事は変わらない
        self.assertEqual(result, article)

    def test_wrong_azure_id_repaired_when_better_match_found(self):
        """Azure の ?id= が間違っているが、正しい URL がソースにある場合は修正される。"""
        source_data = [
            {
                "title": "Azure Backup for Elastic SAN General Availability",
                "url": "https://azure.microsoft.com/updates?id=560904",
                "description": "Azure Backup...",
                "source": "Azure Release Communications",
            },
            {
                # 全く異なるトピック — 誤 ID でこちらの URL が使われた場合
                "title": "Azure Kubernetes Service monthly updates",
                "url": "https://azure.microsoft.com/updates?id=999999",
                "description": "AKS updates...",
                "source": "Azure Release Communications",
            },
        ]
        # 記事の見出しは Elastic SAN だが、リンクは AKS の URL（id=999999）を指している
        article = self._make_article(
            "Azure Backup for Elastic SAN General Availability",
            "https://azure.microsoft.com/updates?id=999999",
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        # 修正済みログが出て、正しい URL に置換されている
        self.assertIn("修正済み", mock_out.getvalue())
        self.assertIn("https://azure.microsoft.com/updates?id=560904", result)
        self.assertNotIn("?id=999999", result)

    def test_wrong_azure_id_warns_when_no_repair_candidate(self):
        """Azure の ?id= が間違っているが修正候補がない場合は警告のみ（記事は変えない）。"""
        source_data = [
            {
                # 全く関係ないトピック
                "title": "Azure Kubernetes Service monthly updates",
                "url": "https://azure.microsoft.com/updates?id=999999",
                "description": "AKS updates...",
                "source": "Azure Release Communications",
            },
        ]
        article = self._make_article(
            "Azure Backup for Elastic SAN General Availability",
            "https://azure.microsoft.com/updates?id=999999",
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        # 修正候補がないので警告のみ、記事は変わらない
        out = mock_out.getvalue()
        self.assertNotIn("修正済み", out)
        self.assertIn("低スコア", out)
        self.assertEqual(result, article)

    def test_url_not_in_source_data_is_silently_skipped(self):
        """同ドメインだが source_data に存在しない URL はスキップ（validate_links で別途処理済み）。"""
        source_data = [
            {
                "title": "Azure Backup for Elastic SAN",
                "url": "https://azure.microsoft.com/updates?id=560904",
                "description": "",
                "source": "Azure",
            },
        ]
        # 同じ azure.microsoft.com ドメインだが source_data にない ?id= を持つ URL
        # ドメインは期待範囲内なのでドメイン不一致チェックはスキップされる
        article = self._make_article(
            "Azure Backup for Elastic SAN",
            "https://azure.microsoft.com/updates?id=UNKNOWN_ID",
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        # source_data に存在しない URL はスキップし、警告は出ない（validate_links で処理される）
        self.assertNotIn("低スコア", mock_out.getvalue())
        self.assertEqual(result, article)

    def test_domain_mismatch_repaired_when_better_match_found(self):
        """リンク先ドメインが source_data と異なる場合（日本ベンダーサイト等）は修正される。

        LLM が誤って日本国内ベンダーサイト等の非公式 URL を付けてしまったケース。
        source_data には azure.microsoft.com の URL しかないのに、
        リンクが外部ドメイン（例: jp-vendor.co.jp）を指している場合に修正を検証する。
        """
        source_data = [
            {
                "title": "Public Preview: Memory in Foundry Agent Service",
                "url": "https://azure.microsoft.com/updates?id=111111",
                "description": "Memory feature for Foundry Agent Service is now available.",
                "source": "Azure Release Communications",
            },
            {
                "title": "Public Preview: Azure Container Apps networking update",
                "url": "https://azure.microsoft.com/updates?id=222222",
                "description": "Container Apps networking improvements.",
                "source": "Azure Release Communications",
            },
        ]
        # ラベルは正しい記事タイトルだが、URL が日本ベンダーサイトを指している
        article = (
            "## 3. Azure\n\n"
            "### Memory in Foundry Agent Service\n\n"
            "**要約**: Foundry Agent Service のメモリ機能が利用可能になりました。\n\n"
            "**影響**: 開発者にとって長期的なメモリ管理が容易になります。\n\n"
            "**リンク**: [Public Preview: Memory in Foundry Agent Service]"
            "(https://jp-vendor.co.jp/azure-updates/memory-foundry)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        out = mock_out.getvalue()
        # ドメイン不一致が検出され、修正済みログが出ている
        self.assertIn("ドメイン不一致→修正済み", out)
        # 正しい Azure URL（id=111111）に置換されている
        self.assertIn("https://azure.microsoft.com/updates?id=111111", result)
        # ベンダーサイトの URL は除去されている
        self.assertNotIn("jp-vendor.co.jp", result)

    def test_domain_mismatch_warns_when_no_repair_candidate(self):
        """リンク先ドメインが source_data と異なるが修正候補がない場合は警告のみ。"""
        source_data = [
            {
                "title": "Azure Kubernetes Service monthly update",
                "url": "https://azure.microsoft.com/updates?id=999999",
                "description": "AKS updates.",
                "source": "Azure Release Communications",
            },
        ]
        # ラベルが source_data のどの記事とも一致しない + 外部ドメイン
        article = (
            "## 3. Azure\n\n"
            "### Memory in Foundry Agent Service\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            "**リンク**: [Memory in Foundry Agent Service]"
            "(https://jp-vendor.co.jp/some-page)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        out = mock_out.getvalue()
        # 修正候補がないので記事は変わらない
        self.assertNotIn("修正済み", out)
        # ドメイン不一致の警告が出ている
        self.assertIn("ドメイン不一致", out)
        # 記事は変わらない
        self.assertEqual(result, article)

    def test_empty_source_data_returns_article_unchanged(self):
        """source_data が空の場合は記事を変えずに返す。"""
        article = self._make_article("Test", "https://example.com/test")
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, [])
        self.assertEqual(mock_out.getvalue(), "")
        self.assertEqual(result, article)

    def test_utm_stripped_url_matches_source(self):
        """utm_* トラッキングパラメータ付き URL でも正規化後にソースと一致すれば問題なし。"""
        source_data = [
            {
                "title": "Azure Kubernetes Service Update",
                "url": "https://azure.microsoft.com/updates?id=123",
                "description": "AKS update details...",
                "source": "Azure",
            },
        ]
        article = self._make_article(
            "Azure Kubernetes Service Update",
            "https://azure.microsoft.com/updates?id=123&utm_source=rss",
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        self.assertNotIn("低スコア", mock_out.getvalue())
        self.assertIn("問題なし", mock_out.getvalue())
        self.assertEqual(result, article)

    def test_label_mismatch_repaired_when_better_match_found(self):
        """リンクラベルがリンク先ソースタイトルと一致しないが、正しいURLがソースにある場合は修正される。

        LLM がラベルにソースタイトルを使いながら URL を誤って別の記事のものにしたケース。
        たとえば Azure で「Memory in Foundry Agent Service」の記事を要約したが、
        別の Azure アップデート記事の URL を誤って付けてしまった場合の修正を検証する。
        """
        source_data = [
            {
                "title": "Public Preview: Memory in Foundry Agent Service",
                "url": "https://azure.microsoft.com/updates?id=111111",
                "description": "Memory feature for Foundry Agent Service is now available.",
                "source": "Azure Release Communications",
            },
            {
                "title": "Public Preview: Azure Container Apps networking update",
                "url": "https://azure.microsoft.com/updates?id=999999",
                "description": "Container Apps networking improvements.",
                "source": "Azure Release Communications",
            },
        ]
        # ラベルは正しい記事（Memory in Foundry Agent Service）を指しているが、
        # URL が誤って Container Apps の記事（id=999999）を指している
        article = (
            "## 3. Azure\n\n"
            "### [In preview] Public Preview: Memory in Foundry Agent Service\n\n"
            "**要約**: Foundry Agent Service におけるメモリ機能がパブリックプレビューとして利用可能になりました。\n\n"
            "**影響**: 開発者にとって長期的なメモリ管理が容易になります。\n\n"
            "**リンク**: [Public Preview: Memory in Foundry Agent Service]"
            "(https://azure.microsoft.com/updates?id=999999)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        out = mock_out.getvalue()
        # ラベル不一致が検出され、ラベルベースの修正済みログが出ている
        self.assertIn("ラベル不一致→修正済み", out)
        # 正しい URL（id=111111）に置換されている
        self.assertIn("https://azure.microsoft.com/updates?id=111111", result)
        # 誤った URL（id=999999）は除去されている
        self.assertNotIn("?id=999999", result)

    def test_label_mismatch_warns_when_no_repair_candidate(self):
        """ラベルとリンク先が不一致で修正候補もない場合は警告のみ（記事は変えない）。"""
        source_data = [
            {
                "title": "Public Preview: Azure Container Apps networking update",
                "url": "https://azure.microsoft.com/updates?id=999999",
                "description": "Container Apps networking improvements.",
                "source": "Azure Release Communications",
            },
        ]
        # ラベル「Memory in Foundry Agent Service」は source_data のどの記事とも一致しない
        article = (
            "## 3. Azure\n\n"
            "### Memory in Foundry Agent Service\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            "**リンク**: [Memory in Foundry Agent Service]"
            "(https://azure.microsoft.com/updates?id=999999)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        out = mock_out.getvalue()
        # 修正候補がないので修正はされていない
        self.assertNotIn("修正済み", out)
        # ラベル不一致の警告が出ている
        self.assertIn("ラベル不一致", out)
        # 記事は変わらない
        self.assertEqual(result, article)

    def test_label_matching_source_title_no_false_positive(self):
        """ラベルとリンク先ソースタイトルが一致する場合は誤検知なし（問題なし）。"""
        source_data = [
            {
                "title": "Public Preview: Memory in Foundry Agent Service",
                "url": "https://azure.microsoft.com/updates?id=111111",
                "description": "Memory feature for Foundry Agent Service.",
                "source": "Azure Release Communications",
            },
        ]
        article = (
            "## 3. Azure\n\n"
            "### Memory in Foundry Agent Service\n\n"
            "**要約**: ...\n\n"
            "**影響**: ...\n\n"
            "**リンク**: [Public Preview: Memory in Foundry Agent Service]"
            "(https://azure.microsoft.com/updates?id=111111)\n"
        )
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            result = SourceUrlTracker.verify_link_source_match(article, source_data)
        out = mock_out.getvalue()
        # 正しいリンクなので修正も警告も出ない
        self.assertNotIn("修正済み", out)
        self.assertNotIn("低スコア", out)
        self.assertIn("問題なし", out)
        # 記事は変わらない
        self.assertEqual(result, article)

    def test_daily_update_delegates_to_source_url_tracker(self):
        """generate_daily_update の _verify_link_source_match は SourceUrlTracker に委譲する。"""
        import generate_daily_update as du
        self.assertIs(
            du._verify_link_source_match,
            SourceUrlTracker.verify_link_source_match,
        )

    def test_smallchat_delegates_to_source_url_tracker(self):
        """generate_smallchat の _verify_link_source_match は SourceUrlTracker に委譲する。"""
        import generate_smallchat as sc
        self.assertIs(
            sc._verify_link_source_match,
            SourceUrlTracker.verify_link_source_match,
        )


class TestNormTitle(unittest.TestCase):
    """SourceUrlTracker._norm_title() のテスト"""

    def test_removes_bracket_prefix(self):
        """[In preview] などの角括弧部分を除去する。"""
        result = SourceUrlTracker._norm_title("[In preview] Azure Backup")
        self.assertNotIn("[in preview]", result)
        self.assertIn("azure", result)
        self.assertIn("backup", result)

    def test_removes_status_prefix(self):
        """Public Preview: などのステータス語を除去する。"""
        result = SourceUrlTracker._norm_title("Public Preview: New Feature")
        self.assertNotIn("public", result)
        self.assertNotIn("preview", result)
        self.assertIn("new", result)
        self.assertIn("feature", result)

    def test_lowercases_and_strips_punctuation(self):
        """小文字化・記号の除去が行われる。"""
        result = SourceUrlTracker._norm_title("Azure VM: Scale Out!")
        self.assertNotIn(":", result)
        self.assertNotIn("!", result)
        self.assertEqual(result, result.lower())

    def test_same_result_as_old_inline_norm(self):
        """以前の inline _norm() と同じ結果を返す（旧実装との後方互換）。"""
        import re as _re
        _bracket_re = _re.compile(r'\[[^\]]+\]')
        _status_prefix_re = _re.compile(
            r'\b(?:Public Preview|Generally Available|Preview|GA|'
            r'Retirement|Retired?|Launched|In preview)\b\s*:?\s*',
            _re.IGNORECASE,
        )
        def _old_norm(t):
            t = _bracket_re.sub('', t)
            t = _status_prefix_re.sub('', t)
            return _re.sub(r'[^\w\s]', ' ', t.strip().lower())

        samples = [
            "[In preview] Public Preview: Azure Thing",
            "Generally Available: Cool Feature!",
            "GA: New VM Size",
            "Azure Kubernetes Service Update v2.0",
        ]
        for s in samples:
            self.assertEqual(SourceUrlTracker._norm_title(s), _old_norm(s), msg=s)
