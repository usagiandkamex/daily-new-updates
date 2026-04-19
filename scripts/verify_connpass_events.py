"""
connpass イベント情報取得の機能検証スクリプト

過去 N か月の各日を対象日として connpass RSS イベント取得をシミュレートし、
各日に取得できるイベント件数を集計・表示する。
RSS 取得は月単位のため、同一月内の日は同じ結果になる（キャッシュで重複リクエストを回避）。

使用方法:
    python scripts/verify_connpass_events.py [--months 3]

GitHub Actions 上で実行した場合は GITHUB_STEP_SUMMARY にも結果を書き出す。
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

# generate_daily_update を同じ scripts ディレクトリから import するためパスを追加
sys.path.insert(0, os.path.dirname(__file__))

import generate_daily_update as du


def _search_months_for_date(target_date: date) -> tuple[str, ...]:
    """target_date から CONNPASS_LOOKAHEAD_DAYS 日先の月までを月別リストで返す。"""
    target_dt = datetime(target_date.year, target_date.month, target_date.day,
                         tzinfo=du.JST)
    end_dt = target_dt + timedelta(days=du.CONNPASS_LOOKAHEAD_DAYS)
    months = []
    y, m = target_dt.year, target_dt.month
    while (y, m) <= (end_dt.year, end_dt.month):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return tuple(months)


def run_verification(months: int = 3) -> None:
    today = datetime.now(tz=du.JST).date()
    start_date = today - timedelta(days=months * 30)

    print(f"検証期間: {start_date} 〜 {today}（{months} か月）")
    print(f"先読み日数: {du.CONNPASS_LOOKAHEAD_DAYS} 日")
    print(f"対象都道府県: {', '.join(du.CONNPASS_TARGET_PREFECTURES)}")
    print()

    # --- RSS 結果キャッシュ（検索月の組み合わせ → イベントリスト）---
    rss_cache: dict[tuple[str, ...], list[dict]] = {}

    per_day: list[tuple[date, int, list[str]]] = []

    current = start_date
    while current <= today:
        key = _search_months_for_date(current)

        if key not in rss_cache:
            print(f"  [{current}] RSS 取得中 (検索月: {', '.join(key)}) ...")
            events = du._fetch_connpass_events_rss(current.strftime("%Y%m%d"))
            rss_cache[key] = events
        else:
            events = rss_cache[key]

        per_day.append((current, len(events), list(key)))
        current += timedelta(days=1)

    # --- 結果表示 ---
    print()
    print("=" * 70)
    print("検証結果サマリー（RSS ベース）")
    print("=" * 70)
    print(f"{'日付':12}  {'件数':>6}  {'検索月範囲':>25}  備考")
    print("-" * 70)

    prev_key: tuple[str, ...] | None = None
    for day, count, key in per_day:
        note = ""
        if prev_key is not None and tuple(key) == prev_key:
            note = "（前日と同じ検索範囲）"
        month_range = f"{key[0]} 〜 {key[-1]}"
        print(f"{day.strftime('%Y/%m/%d'):12}  {count:>6}  {month_range:>25}  {note}")
        prev_key = tuple(key)

    print("=" * 70)

    # --- 統計 ---
    counts = [c for _, c, _ in per_day]
    days_with_events = sum(1 for c in counts if c > 0)
    total_days = len(counts)
    avg = sum(counts) / total_days if total_days > 0 else 0.0
    max_count = max(counts) if counts else 0

    print()
    print("【統計】")
    print(f"  検証日数              : {total_days} 日")
    print(f"  イベントが 1 件以上の日: {days_with_events} 日 "
          f"({100 * days_with_events // total_days if total_days else 0}%)")
    print(f"  平均取得件数          : {avg:.1f} 件/日")
    print(f"  最大取得件数          : {max_count} 件")
    print(f"  ユニーク検索月組合せ  : {len(rss_cache)} 通り")

    # --- 取得イベント一覧 ---
    print()
    print("【取得できたイベント一覧（ユニーク）】")
    all_events: dict[str, dict] = {}
    for events in rss_cache.values():
        for e in events:
            url = e.get("event_url", "")
            if url and url not in all_events:
                all_events[url] = e

    if all_events:
        for i, (url, e) in enumerate(all_events.items(), 1):
            title = e.get("title", "（タイトルなし）")
            catch = (e.get("catch", "") or "")[:80]
            if len(e.get("catch", "") or "") > 80:
                catch += "..."
            print(f"  {i:3}. {title}")
            print(f"       URL  : {url}")
            if catch:
                print(f"       概要 : {catch}")
    else:
        print("  （取得できたイベントはありませんでした）")

    # --- GitHub Actions ジョブサマリーへの書き出し ---
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        _write_github_summary(summary_path, per_day, all_events, months, today, start_date)
        print()
        print(f"GitHub Actions ジョブサマリーへ書き出し完了: {summary_path}")


def _write_github_summary(
    summary_path: str,
    per_day: list[tuple[date, int, list[str]]],
    all_events: dict[str, dict],
    months: int,
    today: date,
    start_date: date,
) -> None:
    counts = [c for _, c, _ in per_day]
    total_days = len(counts)
    days_with_events = sum(1 for c in counts if c > 0)
    avg = sum(counts) / total_days if total_days > 0 else 0.0
    max_count = max(counts) if counts else 0

    lines = [
        "# connpass イベント情報取得 機能検証レポート",
        "",
        f"**検証期間:** {start_date} 〜 {today}（直近 {months} か月）  ",
        f"**先読み日数:** {du.CONNPASS_LOOKAHEAD_DAYS} 日  ",
        f"**対象都道府県:** {', '.join(du.CONNPASS_TARGET_PREFECTURES)}  ",
        "",
        "## 統計",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| 検証日数 | {total_days} 日 |",
        f"| イベントが 1 件以上の日 | {days_with_events} 日 "
        f"({100 * days_with_events // total_days if total_days else 0}%) |",
        f"| 平均取得件数 | {avg:.1f} 件/日 |",
        f"| 最大取得件数 | {max_count} 件 |",
        f"| ユニークイベント総数 | {len(all_events)} 件 |",
        "",
        "## 日別取得件数",
        "",
        "| 日付 | 取得件数 | 検索月範囲 |",
        "|------|---------|-----------|",
    ]

    prev_key: tuple[str, ...] | None = None
    for day, count, key in per_day:
        month_range = f"{key[0]} 〜 {key[-1]}"
        count_str = f"**{count}**" if count > 0 else str(count)
        note = " ※前日と同じ" if (prev_key is not None and tuple(key) == prev_key) else ""
        lines.append(f"| {day.strftime('%Y/%m/%d')} | {count_str} | {month_range}{note} |")
        prev_key = tuple(key)

    lines += [
        "",
        "## 取得できたイベント一覧（ユニーク）",
        "",
    ]

    if all_events:
        for url, e in all_events.items():
            title = e.get("title", "（タイトルなし）")
            catch = (e.get("catch", "") or "")[:120]
            if len(e.get("catch", "") or "") > 120:
                catch += "..."
            lines.append(f"- **[{title}]({url})**")
            if catch:
                lines.append(f"  {catch}")
    else:
        lines.append("（取得できたイベントはありませんでした）")

    lines += [
        "",
        "---",
        "> RSS 取得は月単位のため、同一月内の日は同じイベントセットを参照します。",
        "> 「前日と同じ」注記は参考情報です。月をまたいだ日は新たな RSS 取得を行います。",
    ]

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="過去 N か月の connpass RSS イベント取得結果を日別に集計して表示する"
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="検証する過去の月数（デフォルト: 3）",
    )
    args = parser.parse_args()
    run_verification(args.months)
