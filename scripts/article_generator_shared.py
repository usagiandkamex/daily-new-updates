"""
デイリーアップデート・テクニカル雑談の共通生成ユーティリティ

generate_daily_update.py と generate_smallchat.py の両ワークフローで
共有するクラスを提供する。共通機能をここで一元管理することで、
改善や修正を両ワークフローに同時に反映させることができる。
"""

import re

# マークダウンリンクのラベル部分に対応する正規表現フラグメント。
# [In preview] のような角括弧を含むラベルも 1 段階までサポートする。
# 例: [[In preview] Public Preview: Event Grid](https://...)
_LINK_LABEL_RE = r'[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*'


class SourceUrlTracker:
    """フィード取得したソース URL を管理し、LLM 生成後の参考リンク検証に使用するクラス。

    デイリーアップデート・テクニカル雑談の両ワークフローで共通して使用する。
    LLM が提供されたソースデータ外の URL を生成した可能性がある箇所を可視化し、
    デバッグや品質改善に役立てる。
    """

    @staticmethod
    def collect_source_urls(*data_lists) -> frozenset[str]:
        """複数のデータリストから URL を収集して frozenset を返す。

        フィードから取得した記事・イベント URL を集約し、LLM 生成後の
        参考リンク検証（log_unsourced_reference_links）に使用する。
        list[dict] 形式では "url"・"event_url" キーを参照する。
        """
        urls: set[str] = set()
        for data in data_lists:
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    url = item.get("url") or item.get("event_url", "")
                    if url:
                        urls.add(url)
        return frozenset(urls)

    @staticmethod
    def log_unsourced_reference_links(article: str, source_urls: frozenset[str]) -> None:
        """参考リンクの URL がソースデータに含まれないものを検出・ログ出力する。

        LLM が提供されたソースデータ外の URL を生成した可能性がある箇所を可視化し、
        デバッグや品質改善に役立てる。URL の修正は validate_links() に委ねる。
        """
        ref_link_pattern = re.compile(
            r'\*\*参考リンク\*\*:\s*\[' + _LINK_LABEL_RE + r'\]\((https?://[^)]+)\)'
        )
        unsourced = [
            m.group(1) for m in ref_link_pattern.finditer(article)
            if m.group(1) not in source_urls
        ]
        if unsourced:
            print(f"  ソース外参考リンク: {len(unsourced)} 件（HTTP 検証はこの後 validate_links() で実施）")
            for url in unsourced[:5]:
                print(f"    ℹ {url[:80]}")
        else:
            print("  参考リンク確認: 全てのリンクがソースデータと一致しています")
