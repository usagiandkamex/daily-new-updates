"""
article_generator_shared.py の SourceUrlTracker クラスのテスト

generate_daily_update.py と generate_smallchat.py の両ワークフローで
共有される SourceUrlTracker の挙動を一元的にテストする。
"""

import io
import sys
import os
import unittest
from unittest.mock import patch

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


class TestSourceUrlTrackerLog(unittest.TestCase):
    """SourceUrlTracker.log_unsourced_reference_links() のテスト"""

    def _make_article(self, url: str) -> str:
        return (
            "## 1. テストセクション\n\n"
            f"### トピックA\n\n**要約**: テスト\n\n**参考リンク**: [タイトルA]({url})\n"
        )

    def test_sourced_url_logs_no_warning(self):
        """参考リンク URL がソースに含まれる場合、ソース外の警告ログが出ない。"""
        url = "https://azure.microsoft.com/blog/update"
        source_urls = frozenset({url})
        article = self._make_article(url)

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, source_urls)

        self.assertNotIn("ソース外参考リンク:", mock_out.getvalue())
        self.assertIn("ソースデータと一致", mock_out.getvalue())

    def test_unsourced_url_logs_warning(self):
        """参考リンク URL がソースに含まれない場合、警告ログが出力される。"""
        url = "https://hallucinated.example.com/article"
        source_urls = frozenset()
        article = self._make_article(url)

        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, source_urls)

        self.assertIn("ソース外参考リンク:", mock_out.getvalue())

    def test_unsourced_url_log_shows_count(self):
        """ソース外 URL の件数がログに含まれる。"""
        article = (
            "### A\n\n**参考リンク**: [A](https://bad1.example.com)\n\n"
            "### B\n\n**参考リンク**: [B](https://bad2.example.com)\n"
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
        """参考リンクがない場合、「一致」メッセージが出力される。"""
        article = "## テスト\n\n内容のみ\n"
        with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
            SourceUrlTracker.log_unsourced_reference_links(article, frozenset())

        self.assertIn("ソースデータと一致", mock_out.getvalue())

    def test_unsourced_url_log_truncated_to_five(self):
        """ソース外 URL が 5 件を超えても最大 5 件のみログ出力する。"""
        article_lines = []
        for i in range(7):
            article_lines.append(f"### Topic {i}\n\n**参考リンク**: [T{i}](https://bad{i}.example.com)")
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


if __name__ == "__main__":
    unittest.main()
