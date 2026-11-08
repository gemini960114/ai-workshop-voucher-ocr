"""把 output/csv/ 下所有 CSV 彙整成一份 Excel；待確認的儲存格塗螢光黃並加註解。

CSV 是原始資料，Excel 每次重新產生；產生前舊 Excel 自動備份到 excel/backup/。
要修正辨識結果：改對應的 CSV（並清空「待確認欄位」），再執行本程式。

用法：uv run .agents/skills/voucher-ocr/scripts/build_excel.py [--out output]
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ocr_core import CSV_COLUMNS, FIELDS, MONEY_FIELDS, ROOT, load_config, to_int

YELLOW = PatternFill("solid", fgColor="FFFF00")
HEAD = PatternFill("solid", fgColor="D9E1F2")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WIDTH = {"項次": 6, "會計科目": 40, "控帳編號": 15, "發票號碼": 13, "發票金額": 12, "總計金額": 12, "發票統編": 11,
         "發票抬頭": 44, "負債科目": 40, "計畫代號": 12, "待確認欄位": 20, "備註": 60, "來源檔案": 40,
         "辨識時間": 19, "使用模型": 30}


def read_rows(csv_dir: Path) -> list[dict[str, str]]:
    rows = []
    for p in sorted(csv_dir.glob("*.csv")):
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                rows += list(csv.DictReader(f))
        except (OSError, csv.Error) as e:
            print(f"讀取失敗，略過 {p.name}：{e}")
    return sorted(rows, key=lambda r: r.get("來源檔案", ""))


def flag_duplicates(rows: list[dict[str, str]], receipt_text: str) -> None:
    """跨檔案重複的控帳編號／發票號碼也標為待確認（可能重複請款）。"""
    for key in ("控帳編號", "發票號碼"):
        cnt = Counter(r[key] for r in rows if r.get(key) and r[key] != receipt_text)
        for r in rows:
            if cnt.get(r.get(key, ""), 0) > 1:
                flags = [f for f in r.get("待確認欄位", "").split("、") if f]
                if key not in flags:
                    r["待確認欄位"] = "、".join(flags + [key])
                note = f"{key}：與其他檔案重複"
                r["備註"] = "；".join(x for x in (r.get("備註", ""), note) if x)


def reasons(note: str, field: str) -> str:
    """從備註取出某欄位的原因（備註格式：欄位：原因；欄位：原因）。"""
    return "\n".join(p.split("：", 1)[1] for p in note.split("；") if p.startswith(field + "："))


def build(rows: list[dict[str, str]], path: Path) -> int:
    wb = Workbook()
    ws = wb.active
    ws.title = "核銷彙整"
    cols = ["項次"] + CSV_COLUMNS
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill, c.border = Font(bold=True), HEAD, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")
    n_flag = 0
    for i, r in enumerate(rows, 1):
        flags = {f for f in r.get("待確認欄位", "").split("、") if f}
        for j, col in enumerate(cols, 1):
            val: object = i if col == "項次" else r.get(col, "")
            if col in MONEY_FIELDS:
                val = to_int(val)
            c = ws.cell(row=i + 1, column=j, value=val if val != "" else None)
            c.border = BORDER
            if col in MONEY_FIELDS:
                c.number_format = "#,##0"
            elif col in FIELDS:
                c.number_format = "@"  # 號碼一律文字，避免前導 0 消失或變科學記號
            if col in flags:
                c.fill = YELLOW
                c.comment = Comment(reasons(r.get("備註", ""), col) or "待確認", "OCR")
                n_flag += 1
            if col == "備註":
                c.alignment = Alignment(wrap_text=True, vertical="top")
    for j, col in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(j)].width = WIDTH.get(col, 14)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    info = wb.create_sheet("說明")
    for line in (["產生時間", f"{datetime.now():%Y-%m-%d %H:%M:%S}"], ["筆數", len(rows)], ["待確認儲存格", n_flag], [],
                 ["螢光黃底", "OCR 有疑問的欄位，滑鼠移到儲存格上可看原因；找不到的欄位留空不硬填"],
                 ["修正方式", "改 output/csv/ 中對應的 CSV（並清掉該欄的待確認），再執行 uv run .agents/skills/voucher-ocr/scripts/build_excel.py"],
                 ["負債科目、計畫代號", "負債科目為設定檔固定值；計畫代號取會計科目第 9 碼起 10 碼"]):
        info.append(line)
    info.column_dimensions["A"].width = 20
    info.column_dimensions["B"].width = 90

    tmp = path.with_suffix(".tmp.xlsx")
    try:
        wb.save(tmp)
        tmp.replace(path)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"無法寫入 {path.name}，請先關閉 Excel 中開啟的檔案：{e}") from e
    return n_flag


def main() -> None:
    ap = argparse.ArgumentParser(description="CSV 彙整成 Excel")
    ap.add_argument("--out", type=Path, help="輸出資料夾（預設依設定檔）")
    ap.add_argument("--config", type=Path)
    a = ap.parse_args()
    cfg = load_config(a.config)
    out = (a.out or ROOT / cfg["run"]["output_dir"]).resolve()
    rows = read_rows(out / "csv")
    if not rows:
        raise SystemExit(f"{out / 'csv'} 沒有 CSV，請先執行 ocr_to_csv.py")
    flag_duplicates(rows, cfg["fields"]["receipt_invoice_no"])
    xdir = out / "excel"
    xdir.mkdir(parents=True, exist_ok=True)
    path = xdir / cfg["run"]["excel_name"]
    if path.exists():
        bdir = xdir / "backup"
        bdir.mkdir(exist_ok=True)
        bak = bdir / f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"
        shutil.copy2(path, bak)
        print(f"已備份舊檔：{bak.relative_to(out)}")
    n_flag = build(rows, path)
    print(f"已輸出：{path}（{len(rows)} 筆，{n_flag} 個待確認儲存格）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
