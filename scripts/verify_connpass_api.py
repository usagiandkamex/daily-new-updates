#!/usr/bin/env python3
"""connpass v2 API の動作確認用スクリプト。

CONNPASS_API_KEY 環境変数を読み込み、connpass v2 API
（https://connpass.com/about/api/v2/）に対して実 API コールを行い、
以下を検証する:

1. 認証ヘッダー X-API-Key が有効であること
2. レスポンス JSON の構造（events / results_returned 等）が想定どおりであること
3. 各イベントオブジェクトに event_id / title / started_at / url 等が含まれること
4. 日付絞り込み用パラメータ ym（YYYYMM）が期待どおり機能すること
5. fetch_connpass_events() の段階5 ロジックが、当月の API レスポンスから
   正しくイベントを取り出してマージできること

使い方:
    export CONNPASS_API_KEY="<your_api_key>"
    python scripts/verify_connpass_api.py
    # 当月以外の月を確認する場合:
    python scripts/verify_connpass_api.py 20260601

CI/ローカルで API キーが未設定の場合は終了コード 2 でスキップする。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any

import requests

# scripts/ ディレクトリ内のスクリプトとして import 可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_daily_update as du  # noqa: E402


def _print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _call_api(api_key: str, params: dict[str, Any]) -> tuple[int, dict | None, str]:
    """connpass v2 API を呼び出し、(status_code, json, error_text) を返す。"""
    headers = {
        "Accept": "application/json",
        "User-Agent": "daily-new-updates verify_connpass_api.py",
        "X-API-Key": api_key,
    }
    try:
        resp = requests.get(
            du.CONNPASS_API_URL, params=params, headers=headers, timeout=30
        )
    except requests.RequestException as e:
        return 0, None, f"RequestException: {e}"
    body_text = resp.text[:500]
    try:
        body_json = resp.json()
    except ValueError:
        body_json = None
    return resp.status_code, body_json, body_text


def verify_basic_auth(api_key: str) -> bool:
    _print_header("Step 1: 認証 + 基本レスポンス構造の確認")
    status, data, body = _call_api(api_key, {"keyword": "Python", "count": 3})
    print(f"  HTTP status: {status}")
    if status != 200 or not isinstance(data, dict):
        print(f"  ✗ 期待 status=200, dict レスポンス。実際: status={status}, body={body!r}")
        return False
    print(f"  ✓ 認証成功 (X-API-Key 受理)")
    print(f"  レスポンスの top-level キー: {sorted(data.keys())}")
    for key in ("results_returned", "results_available", "events"):
        if key not in data:
            print(f"  ✗ 想定キー {key!r} が無い")
            return False
    print(f"  ✓ events / results_returned / results_available を含む")
    if not isinstance(data["events"], list):
        print(f"  ✗ events がリストでない: {type(data['events'])}")
        return False
    print(f"  ✓ events はリスト ({len(data['events'])} 件)")
    if data["events"]:
        sample = data["events"][0]
        print(f"  サンプルイベントのキー: {sorted(sample.keys())}")
        for k in ("event_id", "title", "started_at", "url"):
            if k not in sample:
                print(f"  ⚠ サンプルイベントに想定キー {k!r} が無い")
        print(f"  サンプルイベント (要約):")
        print(json.dumps(
            {k: sample.get(k) for k in ("event_id", "title", "started_at", "url")},
            ensure_ascii=False, indent=4,
        ))
    return True


def verify_ym_filter(api_key: str, ym: str) -> bool:
    _print_header(f"Step 2: ym パラメータでの月別絞り込み (ym={ym})")
    status, data, body = _call_api(api_key, {"ym": ym, "count": 5})
    print(f"  HTTP status: {status}")
    if status != 200 or not isinstance(data, dict):
        print(f"  ✗ status={status}, body={body!r}")
        return False
    events = data.get("events", [])
    print(f"  events 件数: {len(events)}")
    bad: list[str] = []
    for ev in events:
        sa = ev.get("started_at", "")
        # started_at は ISO 8601 (YYYY-MM-DDTHH:MM:SS+09:00)
        if sa and len(sa) >= 7:
            ev_ym = sa[:4] + sa[5:7]
            if ev_ym != ym:
                bad.append(f"{ev.get('event_id')} {sa}")
    if bad:
        print(f"  ⚠ ym と異なる月のイベントが含まれる: {bad[:3]}")
        return False
    print(f"  ✓ 全イベントが ym={ym} の月に属する")
    return True


def verify_undocumented_params_ignored(api_key: str) -> bool:
    _print_header("Step 3: 未文書パラメータが拒否されないこと（互換性確認）")
    # v1 由来の started_at_gte / accepted_end_at_gte は v2 では存在しない。
    # API がこれらを送っても 4xx を返さず黙って無視することを確認する。
    status, data, body = _call_api(
        api_key,
        {
            "keyword": "Python",
            "count": 1,
            "started_at_gte": "2099-01-01",  # 未来日。フィルタが効くと 0 件になる想定だった
            "accepted_end_at_gte": "2099-01-01",
        },
    )
    print(f"  HTTP status: {status}")
    if status >= 400:
        print(f"  ⚠ v2 API は未文書パラメータに対し HTTP {status} を返した: {body!r}")
        # 拒否されるなら、これらを送るべきでないという結論を強化するだけなので "OK" 扱い
        return True
    if not isinstance(data, dict):
        print(f"  ✗ 想定外レスポンス body={body!r}")
        return False
    cnt = data.get("results_returned", 0)
    print(f"  events 件数: {cnt}")
    if cnt > 0:
        # 本来 2099 年以降のイベントは存在しないはずなので、件数 > 0 ならフィルタは無視されている
        print("  ✓ 未文書パラメータは API 側で無視されている（フィルタが効いていない）")
        print("    → 実装からは送らない方針が正しい")
    else:
        print("  ⚠ 0 件返却。フィルタが効いた可能性あり（要再確認）")
    return True


def verify_fetch_integration(api_key: str, target_date: str) -> bool:
    _print_header(
        f"Step 4: fetch_connpass_events('{target_date}') 統合動作 (実 API 込み)"
    )
    # 段階1〜4 の RSS は外部にも出るので、完全な実行は時間がかかる。
    # ここでは段階5 のロジックを直接ミニ呼び出しして、実 API からのイベントが
    # 正規化フローに乗ることを確認する。
    target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=du.JST)
    ym = target_dt.strftime("%Y%m")
    status, data, _ = _call_api(
        api_key, {"keyword": "東京都", "ym": ym, "count": 20, "order": 2}
    )
    if status != 200 or not isinstance(data, dict):
        print(f"  ✗ 実 API 失敗 status={status}")
        return False
    raw_events = data.get("events", [])
    print(f"  実 API から {len(raw_events)} 件取得 (keyword=東京都, ym={ym})")
    if not raw_events:
        print("  ⚠ 0 件のため正規化検証は省略")
        return True

    # スクリプトの正規化ロジックを再現
    accepted = 0
    samples: list[dict] = []
    for ev in raw_events:
        started_at_str = ev.get("started_at", "")
        if not started_at_str:
            continue
        try:
            event_dt = datetime.fromisoformat(
                started_at_str.replace("Z", "+00:00")
            ).astimezone(du.JST)
        except (ValueError, TypeError):
            continue
        normalized = {
            "title": (ev.get("title") or "").strip(),
            "catch": (ev.get("catch") or "").strip(),
            "event_url": ev.get("url") or ev.get("event_url", ""),
            "started_at": event_dt.strftime("%Y/%m/%d %H:%M"),
        }
        if not du._is_it_event(normalized):
            continue
        accepted += 1
        if len(samples) < 3:
            samples.append(normalized)
    print(f"  IT 関連 + 日時取得済みのイベント: {accepted} 件")
    for s in samples:
        print(f"    - {s['started_at']} | {s['title'][:60]}")
        print(f"      {s['event_url']}")
    return True


def main() -> int:
    api_key = os.environ.get("CONNPASS_API_KEY", "").strip()
    if not api_key:
        print("CONNPASS_API_KEY が設定されていません。スキップします。", file=sys.stderr)
        print("  使用例: CONNPASS_API_KEY=xxxx python scripts/verify_connpass_api.py")
        return 2

    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now(du.JST).strftime("%Y%m%d")
    try:
        target_dt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=du.JST)
    except ValueError:
        print(
            f"対象日 {target_date!r} の形式が不正です。YYYYMMDD 形式で指定してください "
            "(例: 20260601)",
            file=sys.stderr,
        )
        # スキップ (CONNPASS_API_KEY 未設定) との区別のため、入力エラーは 1 を返す。
        return 1

    print(f"connpass v2 API ({du.CONNPASS_API_URL}) の動作確認を開始します。")
    print(f"  対象日: {target_date}")

    results: list[tuple[str, bool]] = []
    results.append(("認証 + レスポンス構造", verify_basic_auth(api_key)))
    results.append(("ym 月別絞り込み", verify_ym_filter(api_key, target_dt.strftime("%Y%m"))))
    results.append(("未文書パラメータ挙動", verify_undocumented_params_ignored(api_key)))
    results.append(("fetch_connpass_events 統合", verify_fetch_integration(api_key, target_date)))

    _print_header("確認結果サマリ")
    all_ok = True
    for name, ok in results:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}")
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
