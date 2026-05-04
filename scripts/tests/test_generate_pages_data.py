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

---

**[[第７回] AIロボット駆動科学研究会](https://ai-robot-science.connpass.com/event/388928/)**

**開催日時**: 2026/05/11 13:30

**場所**: Shimadzu Tokyo Innovation Plaza

**概要**: アーカイブはこちら https://youtube.com/example 参加者歓迎！

**参加状況**: 28/100名

---

**[外部サイトリンク](https://example.com/other/)**

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

    def test_includes_event_title_with_brackets(self):
        """タイトルに角括弧を含む connpass イベントが完全に抽出される（例: [第７回] ...）。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertIn("[第７回] AIロボット駆動科学研究会", body)

    def test_non_connpass_bold_link_excluded(self):
        """connpass 以外のドメインの bold リンクはタイトルとして抽出されない。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertNotIn("外部サイトリンク", body)

    def test_event_summary_url_stripped(self):
        """概要フィールドの値に含まれる URL は search_text から除外される。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertNotIn("https://youtube.com/example", body)
        self.assertIn("参加者歓迎", body)

    def test_body_is_condensed(self):
        """extract_body はマークダウン記法（区切り線・参加状況等）を除いた凝縮テキストを返す。"""
        body = extract_body(_SAMPLE_UPDATE)
        self.assertNotEqual(body, _SAMPLE_UPDATE)
        self.assertNotIn("---", body)
        self.assertNotIn("参加状況", body)


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
