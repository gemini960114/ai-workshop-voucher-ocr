"""以去識別化樣本的標準答案 JSON 評估辨識準確率。

用法：uv run .agents/skills/voucher-ocr/scripts/eval_ocr.py [--csv output_deid/csv] [--truth example_deid]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from ocr_core import norm_id, to_int

KEYS = ["會計科目", "控帳編號", "發票號碼", "發票金額", "總計金額", "發票統編", "發票抬頭"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=Path("output_deid/csv"))
    ap.add_argument("--truth", type=Path, default=Path("example_deid"))
    a = ap.parse_args()
    ok = {k: 0 for k in KEYS}
    n = 0
    for t in sorted(a.truth.glob("*.json")):
        c = a.csv / f"{t.stem}.csv"
        if not c.exists():
            print(f"缺 CSV：{c.name}")
            continue
        try:
            truth = json.loads(t.read_text(encoding="utf-8"))
            with open(c, encoding="utf-8-sig") as f:
                row = next(csv.DictReader(f))
        except (OSError, json.JSONDecodeError, StopIteration) as e:
            print(f"讀取失敗 {t.name}：{e}")
            continue
        n += 1
        print(f"\n■ {t.stem}  待確認：{row['待確認欄位'] or '（無）'}")
        for k in KEYS:
            want, got = truth.get(k), row.get(k, "")
            same = to_int(got) == want if isinstance(want, int) else norm_id(got) == norm_id(want)
            ok[k] += same
            print(f"  {'✔' if same else '✘'} {k}：{got}" + ("" if same else f"   （正解 {want}）"))
    if n:
        print(f"\n=== {n} 份文件，各欄位正確率 ===")
        for k in KEYS:
            print(f"  {k}：{ok[k]}/{n}")
        print(f"  整體：{sum(ok.values())}/{n * len(KEYS)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
