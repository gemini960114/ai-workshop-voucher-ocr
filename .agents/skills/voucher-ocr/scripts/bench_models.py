"""多模型辨識比較：同一批 PDF 用不同模型組合各跑一次，對照標準答案 JSON 計算正確率。

每個組合輸出到 output_bench/<組合名>/（可續跑，已完成的檔案會略過）。
用法：uv run .agents/skills/voucher-ocr/scripts/bench_models.py [--pdf example_deid] [--truth example_deid]（本單位統編與全名取自 ocr_config.toml）
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ocr_core import ROOT, load_config, norm_id, to_int
from ocr_to_csv import collect, process

KEYS = ["會計科目", "控帳編號", "發票號碼", "發票金額", "總計金額", "發票統編", "發票抬頭"]

# 組合名稱 → (OCR 模型, 擷取模型)；OCR 留空 = 擷取模型直接看圖
COMBOS: dict[str, tuple[str, str]] = {
    "chandra-ocr-2→Muse-Spark": ("chandra-ocr-2", "Muse-Spark-Open-816B-A42B"),
    "chandra-ocr-2(直接看圖)": ("", "chandra-ocr-2"),
    "Inkling-Small(直接看圖)": ("", "Inkling-Small"),
    "Muse-Spark(直接看圖)": ("", "Muse-Spark-Open-816B-A42B"),
    "Muse-Glimmer-30B(直接看圖)": ("", "Muse-Glimmer-30B"),
}


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def score(csv_dir: Path, truth_dir: Path) -> dict[str, object]:
    ok = {k: 0 for k in KEYS}
    n = wrong = wrong_flagged = false_alarm = 0
    detail = []
    for t in sorted(truth_dir.glob("*.json")):
        c = csv_dir / f"{t.stem}.csv"
        if not c.exists():
            detail.append(f"{t.stem}：無結果")
            continue
        truth = json.loads(t.read_text(encoding="utf-8"))
        with open(c, encoding="utf-8-sig") as f:
            row = next(csv.DictReader(f))
        flags = set(filter(None, row["待確認欄位"].split("、")))
        n += 1
        for k in KEYS:
            want, got = truth.get(k), row.get(k, "")
            same = to_int(got) == want if isinstance(want, int) else norm_id(got) == norm_id(want)
            ok[k] += same
            if not same:
                wrong += 1
                wrong_flagged += k in flags
                detail.append(f"{t.stem.replace('_deid', '')[-3:]} {k}：{got or '（空）'} → 正解 {want}{' 〔已標黃〕' if k in flags else ' 〔未標記！〕'}")
            elif k in flags:
                false_alarm += 1
    return dict(n=n, ok=ok, wrong=wrong, wrong_flagged=wrong_flagged, false_alarm=false_alarm, detail=detail)


def run_combo(name: str, ocr: str, ext: str, base: dict, pdfs: list[Path], out: Path) -> float:
    cfg = copy.deepcopy(base)
    cfg["ocr"]["model"], cfg["extract"]["model"], cfg["verify"]["model"] = ocr, ext, ""
    t0 = time.time()
    for p in pdfs:
        try:
            print(f"  [{name}] {process(p, cfg, out, False, False)}", flush=True)
        except Exception as e:
            print(f"  [{name}] 失敗 {p.name}：{e}", flush=True)
    return (time.time() - t0) / max(len(pdfs), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="example_deid")
    ap.add_argument("--truth", type=Path, default=Path("example_deid"))
    ap.add_argument("--out", type=Path, default=Path("output_bench"))
    a = ap.parse_args()
    base = load_config()
    pdfs = collect([a.pdf])
    outs = {n: (ROOT / a.out / safe(n)).resolve() for n in COMBOS}
    with ThreadPoolExecutor(max_workers=len(COMBOS)) as ex:  # 各組合平行，組合內逐檔
        futs = {n: ex.submit(run_combo, n, o, e, base, pdfs, outs[n]) for n, (o, e) in COMBOS.items()}
        secs = {n: f.result() for n, f in futs.items()}

    lines = ["| 組合 | " + " | ".join(KEYS) + " | 整體 | 錯誤值已標黃 | 誤報 | 秒/份 |",
             "|---" * (len(KEYS) + 5) + "|"]
    details = []
    for n in COMBOS:
        s = score(outs[n] / "csv", a.truth)
        tot = sum(s["ok"].values())
        lines.append(f"| {n} | " + " | ".join(f"{s['ok'][k]}/{s['n']}" for k in KEYS)
                     + f" | {tot}/{s['n'] * len(KEYS)} | {s['wrong_flagged']}/{s['wrong']} | {s['false_alarm']} | {secs[n]:.0f} |")
        details.append(f"\n### {n}\n" + ("\n".join(f"- {d}" for d in s["detail"]) or "- 全對"))
    report = "\n".join(lines) + "\n" + "\n".join(details)
    (ROOT / a.out / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
