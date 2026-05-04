"""
generate_pages_data.py のテスト
"""

import sys
import os
import unittest

# スクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_pages_data import extract_body, _build_search_text


_SAMPLE_UPDATE = """\
# 2026/05/01 デイリーアップデート

## 1. Azure アップデート情報

現在の対象期間に該当する情報はありません。

## 2. ニュースで話題のテーマ

### AI関連の最新動向

**要約**: 今週のAI関連の最新動向をまとめました。

**影響**: AIの普及が加速しています。

**リンク**: [AI最新動向](https://example.com/ai)

## 5. connpassイベント

**[TypeScript勉強会](https://connpass.com/event/123456/)**

**開催日時**: 2026/05/22 19:00

**場所**: 東京都渋谷区

**概要**: TypeScriptを学ぶハンズオン勉強会です。初心者歓迎！

**参加状況**: 5/20名
"""


class TestExtractBody(unittest.TestCase):
    """extract_body() のテスト"""

    def test_includes_h3_heading(self):
        """H3 見出しがボディに含まれる。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("AI関連の最新動向", body)

    def test_includes_youyaku_text(self):
        """要約テキストがボディに含まれる。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("今週のAI関連の最新動向をまとめました", body)

    def test_includes_event_title(self):
        """connpassイベントのタイトルがボディに含まれる。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("TypeScript勉強会", body)

    def test_includes_event_date(self):
        """connpassイベントの開催日時がボディに含まれる。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("2026/05/22", body)

    def test_includes_event_location(self):
        """connpassイベントの場所がボディに含まれる。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("東京都渋谷区", body)

    def test_includes_event_summary(self):
        """connpassイベントの概要がボディに含まれる。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("TypeScriptを学ぶハンズオン勉強会です", body)

    def test_full_content_returned(self):
        """extract_body は記事の全文を返す。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertEqual(body, _SAMPLE_UPDATE)


class TestBuildSearchText(unittest.TestCase):
    """_build_search_text() のテスト"""

    def test_event_info_is_searchable(self):
        """connpassイベント情報が search_text に含まれる（検索対象になる）。"""
        entry = {
            "title": "2026/05/01 デイリーアップデート",
            "excerpt": "今週のAI関連",
            "tags": ["AI"],
            "body": extract_body(_SAMPLE_UPDATE),
        }
        search_text = _build_search_text(entry)
        self.assertIn("typescript勉強会", search_text)
        self.assertIn("東京都渋谷区", search_text)
        self.assertIn("typescriptを学ぶハンズオン勉強会です", search_text)

    def test_search_text_is_lowercased(self):
        """search_text は小文字化されている。"""
        entry = {
            "title": "TypeScript",
            "excerpt": "",
            "tags": [],
            "body": "Azure Update",
        }
        search_text = _build_search_text(entry)
        self.assertEqual(search_text, search_text.lower())


if __name__ == "__main__":
    unittest.main()
