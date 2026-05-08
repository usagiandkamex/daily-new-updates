"""
generate_events_calendar.py の純粋ロジックの単体テスト

外部 HTTP 通信は unittest.mock でスタブし、実際のネットワーク接続は行わない。
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_events_calendar import (
    _build_search_months,
    _is_it_event,
    _ConnpassEventPageParser,
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
    """説明文の切り詰めロジック（MAX_DESCRIPTION_CHARS）のテスト"""

    def _truncate(self, text: str) -> str:
        """generate_events_calendar._enrich_descriptions 内の切り詰めロジックを再現する。"""
        if len(text) > MAX_DESCRIPTION_CHARS:
            return text[:MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
        return text

    def test_short_text_unchanged(self):
        """MAX_DESCRIPTION_CHARS 以下のテキストは変更されない。"""
        text = "短いテキスト"
        self.assertEqual(self._truncate(text), text)

    def test_exact_length_unchanged(self):
        """ちょうど MAX_DESCRIPTION_CHARS 文字のテキストは変更されない。"""
        text = "あ" * MAX_DESCRIPTION_CHARS
        self.assertEqual(self._truncate(text), text)

    def test_long_text_truncated_with_ellipsis(self):
        """MAX_DESCRIPTION_CHARS を超えるテキストは '…' で終わる。"""
        # MAX_DESCRIPTION_CHARS + 100 文字を超えるテキストを作成
        text = "あ " * (MAX_DESCRIPTION_CHARS // 2 + 50)
        result = self._truncate(text)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), MAX_DESCRIPTION_CHARS + 1)  # +1 for "…"

    def test_truncation_at_word_boundary(self):
        """単語境界（スペース）で切り詰めること。"""
        # 'a' * (MAX_DESCRIPTION_CHARS - 5) + ' ' + 'b' * 100 のように単語境界がある
        prefix = "hello " * (MAX_DESCRIPTION_CHARS // 6 + 1)
        result = self._truncate(prefix)
        # スペースで終わらず '…' で終わること
        self.assertTrue(result.endswith("…"))
        # '…' の直前が単語内テキスト（スペースなし）であること
        self.assertFalse(result[:-1].endswith(" "))


if __name__ == "__main__":
    unittest.main()
