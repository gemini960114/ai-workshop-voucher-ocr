"""核銷憑證 PDF → CSV（一個 PDF 一個 CSV）。

流程：PDF 轉圖 →（OCR 模型整頁轉文字）→ 擷取模型取欄位 →（複核模型看圖複讀）→ 規則檢查 → CSV
已存在的 CSV 一律跳過，不覆寫；加 --force 才重做，重做前舊 CSV 自動備份到 csv/_backup/。

用法（在專案根目錄執行，以下以 $S 代表 .agents/skills/voucher-ocr/scripts）：
  uv run $S/ocr_to_csv.py test/                      # 轉換資料夾內所有 PDF（含子資料夾）
  uv run $S/ocr_to_csv.py a.pdf b.pdf                # 指定檔案
  uv run $S/ocr_to_csv.py test/ --force              # 已有 CSV 也重做（舊檔備份）
  uv run $S/ocr_to_csv.py test/ --ocr-model chandra-ocr-2   # 改用「先 OCR 再擷取」模式
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from ocr_core import (CSV_COLUMNS, ROOT, call_llm, html_to_text, load_config, norm_id, parse_json, parse_upper,
                      render_pages, stage, to_int, valid_ubn)

EXTRACT_PROMPT = """你是會計憑證資料擷取助理。以下是一份「核銷憑證黏存單」掃描檔的 OCR 結果，上半部是黏存單，下半部黏貼發票或收據。
請依內容擷取欄位，只輸出一個 JSON 物件，不要任何說明。

規則：
- 只抄寫文件上實際出現的內容，找不到就填 null，絕對不要猜測或自行編造。
- 號碼類（會計科目、控帳編號、發票號碼、統編）逐字照抄，去掉空白。
- 金額填整數（去掉 $ 與逗號）；找不到填 null，不要填 0。
- 統一編號：發票上「買受人」的統編是買方；賣方統編通常在「統一發票專用章」或「賣方」處。
- 對任何看起來模糊、手寫難辨、或前後矛盾的欄位，把欄位名稱放進「不確定」陣列。

JSON 格式：
{
  "單據類型": "三聯式統一發票 | 二聯式統一發票 | 電子發票證明聯 | 免用發票收據 | 其他",
  "會計科目": "黏存單『會計科目/科目說明』的科目代碼，如 03-1111-03114Z1500-0000-51330612-00-00；多筆時取第一筆",
  "會計科目筆數": 1,
  "控帳編號": "黏存單左上『控帳編號』",
  "黏存單核銷金額": null,
  "黏存單核銷金額大寫": "如 新台幣參拾壹萬伍仟肆佰貳拾元整",
  "黏存單總計": null,
  "發票號碼": "兩碼英文＋8 碼數字，如 KX52816403；收據無號碼填 null",
  "發票張數": 1,
  "銷售額": null,
  "營業稅": null,
  "發票總計": null,
  "發票大寫": "發票上『總計新臺幣(中文大寫)』的內容，依原文抄寫",
  "賣方名稱": "",
  "賣方統編": "",
  "買方名稱": "發票或收據上的買受人名稱",
  "買方統編": "",
  "不確定": []
}

OCR 結果：
"""

VERIFY_PROMPT = """請仔細看這張核銷憑證掃描圖，只讀出下列項目，輸出一個 JSON 物件，看不清楚就填 null，不要猜測：
{"控帳編號": "黏存單左上的控帳編號", "黏存單總計": 黏存單『總計』列的金額整數,
 "發票號碼": "發票號碼（兩碼英文+8碼數字）", "發票總計": 發票『總計』金額整數（若貼了多張發票或收據，填全部合計）,
 "賣方統編": "賣方（開立發票或收據的廠商）統一編號，通常在發票專用章或收據章上；不要填『買受人』的統編"}"""


_TEMPLATE = parse_json(EXTRACT_PROMPT)
_TEMPLATE_VALUES = {v for v in _TEMPLATE.values() if isinstance(v, str) and v}


def check_answer(x: dict[str, Any]) -> dict[str, Any]:
    """拒絕模型照抄提示範本（欄位值仍是說明文字）的輸出。"""
    if any(isinstance(v, str) and v in _TEMPLATE_VALUES for v in x.values()):
        raise ValueError("模型回傳的是提示範本，不是答案")
    return x


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def run_ocr(pdf: Path, images: list[bytes], cfg: dict[str, Any], ocr_dir: Path, reocr: bool) -> str:
    """整頁 OCR；結果存檔重用（原始 HTML 與精簡文字各一份）。"""
    txt_path = ocr_dir / f"{pdf.stem}.txt"
    if txt_path.exists() and not reocr:
        return txt_path.read_text(encoding="utf-8")
    st = stage(cfg, "ocr")
    raw, text = [], []
    for i, img in enumerate(images, 1):
        out = ""
        for _ in range(2):  # 結果不像 OCR（太短、模型說看不到圖）時重試一次
            out = call_llm(st, "OCR this image to HTML.", [img])
            if len(html_to_text(out)) >= 100:
                break
        else:
            raise RuntimeError(f"第{i}頁 OCR 結果異常（模型可能沒收到圖片，請調低 [ocr] max_tokens）：{out[:80]!r}")
        raw.append(f"<!-- 第{i}頁 -->\n{out}")
        text.append(f"### 第{i}頁\n{html_to_text(out)}")
    ocr_dir.mkdir(parents=True, exist_ok=True)
    (ocr_dir / f"{pdf.stem}.html").write_text("\n".join(raw), encoding="utf-8")
    txt_path.write_text("\n\n".join(text), encoding="utf-8")
    return txt_path.read_text(encoding="utf-8")


def nonzero(v: Any) -> int | None:
    """總計類金額：0 視為未辨識（營業稅、銷售額可能合法為 0，不適用）。"""
    n = to_int(v)
    return n or None


def normalize_name(s: str) -> str:
    return re.sub(r"[\s　/／()（）]", "", s).replace("臺", "台")


class Flags:
    """收集待確認欄位與原因。"""

    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {}
        self.notes: list[str] = []  # 只寫進備註、不標黃的參考資訊

    def add(self, field: str, reason: str) -> None:
        self.items.setdefault(field, [])
        if reason not in self.items[field]:
            self.items[field].append(reason)


def build_row(x: dict[str, Any], v: dict[str, Any] | None, cfg: dict[str, Any], pdf: Path) -> dict[str, Any]:
    """擷取結果 → 輸出列，並做規則檢查。"""
    fl = Flags()
    buyers = set(cfg["org"]["buyer_ubns"])
    is_receipt = "收據" in str(x.get("單據類型") or "")

    acct = norm_id(x.get("會計科目"))
    ctrl = norm_id(x.get("控帳編號"))
    inv_no = norm_id(x.get("發票號碼"))
    if not inv_no and is_receipt:
        inv_no = cfg["fields"]["receipt_invoice_no"]
    inv_amt = nonzero(x.get("發票總計"))  # 總計類金額實務上不會是 0，模型誤填 0 視為未辨識
    total = nonzero(x.get("黏存單總計")) or nonzero(x.get("黏存單核銷金額"))
    seller = norm_id(x.get("賣方統編"))
    buyer_name = str(x.get("買方名稱") or "").strip().rstrip("/／✓√ ")
    plan = acct[8:18] if re.fullmatch(r"\d{2}-\d{4}-[0-9A-Z]{10}-.*", acct) else ""

    row = {"會計科目": acct, "控帳編號": ctrl, "發票號碼": inv_no, "發票金額": inv_amt, "總計金額": total,
           "發票統編": seller, "發票抬頭": buyer_name, "負債科目": cfg["fields"]["liability_account"], "計畫代號": plan}

    # 1. 缺漏
    for k in ("會計科目", "控帳編號", "發票號碼", "發票金額", "總計金額", "發票統編", "發票抬頭"):
        if row[k] in ("", None):
            fl.add(k, "未辨識到")
    # 2. 格式
    if acct and not re.fullmatch(r"\d{2}-\d{4}-[0-9A-Z]{10}-\d{4}-\d{8}-\d{2}-\d{2}", acct):
        fl.add("會計科目", "格式不符")
    if (to_int(x.get("會計科目筆數")) or 1) > 1:
        fl.add("會計科目", f"黏存單有 {x['會計科目筆數']} 筆科目，只取第一筆")
    if ctrl and not re.fullmatch(r"\d{12}", ctrl):
        fl.add("控帳編號", "應為 12 碼數字")
    if inv_no and not is_receipt and not re.fullmatch(r"[A-Z]{2}\d{8}", inv_no):
        fl.add("發票號碼", "應為 2 碼英文＋8 碼數字")
    # 3. 統編
    if seller:
        if seller in buyers:
            fl.add("發票統編", "讀到的是本單位（買方）統編，應為賣方統編")
        elif not valid_ubn(seller):
            fl.add("發票統編", "統編檢查碼不符，可能讀錯")
    b_ubn = norm_id(x.get("買方統編"))
    if b_ubn and b_ubn not in buyers:  # 買方統編不是輸出欄位，只記參考
        fl.notes.append(f"買方統編讀到 {b_ubn}，與本單位統編不同（多為手寫誤讀）")
    names = {normalize_name(n) for n in cfg["org"].get("buyer_names", [])}
    if buyer_name and names and normalize_name(buyer_name) not in names:
        fl.add("發票抬頭", f"與本單位名稱不同（設定為 {'、'.join(cfg['org']['buyer_names'])}），可能只讀到一部分")
    # 4. 金額勾稽
    net, tax = to_int(x.get("銷售額")), to_int(x.get("營業稅"))
    if inv_amt is not None and net is not None and tax is not None and net + tax != inv_amt:
        fl.add("發票金額", f"銷售額 {net:,} + 營業稅 {tax:,} ≠ 總計 {inv_amt:,}")
    up = parse_upper(str(x.get("發票大寫") or ""), grid=True)
    multi = (to_int(x.get("發票張數")) or 1) > 1  # 多張發票／收據時，大寫只代表其中一張，不比對
    # 預印格前段（已劃線的空位）常被誤讀，只比對與金額同位數的部分
    if up and inv_amt and not multi and up % 10 ** len(str(inv_amt)) != inv_amt:
        fl.add("發票金額", f"發票中文大寫換算為 {up:,}，與數字 {inv_amt:,} 不符")
    pay, pay_up = nonzero(x.get("黏存單核銷金額")), parse_upper(str(x.get("黏存單核銷金額大寫") or ""))
    if total is not None and pay is not None and pay != total:
        fl.add("總計金額", f"核銷金額 {pay:,} 與總計 {total:,} 不符")
    if total and pay_up and pay_up != total:
        fl.add("總計金額", f"核銷金額大寫換算為 {pay_up:,}，與 {total:,} 不符")
    if inv_amt is not None and total is not None and inv_amt != total:
        n = to_int(x.get("發票張數")) or 1
        msg = f"發票金額 {inv_amt:,} 與黏存單總計 {total:,} 不符" + ("（含多張發票）" if n > 1 else "")
        fl.add("發票金額", msg)
        fl.add("總計金額", msg)
    # 5. 複核模型比對
    if v:
        pairs = [("控帳編號", ctrl, norm_id(v.get("控帳編號"))), ("發票號碼", inv_no, norm_id(v.get("發票號碼"))),
                 ("發票統編", seller, norm_id(v.get("賣方統編"))),
                 ("發票金額", inv_amt, to_int(v.get("發票總計"))), ("總計金額", total, to_int(v.get("黏存單總計")))]
        for k, a, b in pairs:
            if k == "發票統編" and b in buyers:  # 複核誤讀成本單位（買方）統編，不具比對意義
                continue
            if a not in ("", None) and b not in ("", None) and a != b and not (k == "發票號碼" and is_receipt):
                fl.add(k, f"複核模型讀到 {b:,}" if isinstance(b, int) else f"複核模型讀到 {b}")
    # 6. 模型自評不確定
    alias = {"黏存單總計": "總計金額", "黏存單核銷金額": "總計金額", "發票總計": "發票金額", "賣方統編": "發票統編",
             "買方名稱": "發票抬頭", "銷售額": "發票金額", "營業稅": "發票金額"}
    # 金額已被獨立勾稽證實時，不採信模型的「不確定」自評
    confirmed = set()
    if inv_amt is not None and inv_amt == total and (net is None or tax is None or net + tax == inv_amt):
        confirmed.add("發票金額")
    if total is not None and total == pay and (pay_up is None or pay_up == total):
        confirmed.add("總計金額")
    for k in x.get("不確定") or []:
        k = alias.get(k, k)
        if k in row and k not in confirmed and k not in fl.items:
            fl.add(k, "擷取模型標示不確定")

    row["待確認欄位"] = "、".join(fl.items)
    row["備註"] = "；".join([f"{k}：{'、'.join(r)}" for k, r in fl.items.items()] + [f"參考：{n}" for n in fl.notes])
    return row


def process(pdf: Path, cfg: dict[str, Any], out: Path, force: bool, reocr: bool) -> str:
    csv_dir = out / "csv"
    csv_path = csv_dir / f"{pdf.stem}.csv"
    if csv_path.exists() and not force:
        return f"略過（已有 CSV）：{pdf.name}"
    t0 = time.time()
    images = render_pages(pdf, int(cfg["ocr"].get("dpi", 150)))
    ocr_st, ext_st, ver_st = stage(cfg, "ocr"), stage(cfg, "extract"), stage(cfg, "verify")
    if ocr_st.enabled:
        text = run_ocr(pdf, images, cfg, out / "ocr", reocr)
        x = parse_json(call_llm(ext_st, EXTRACT_PROMPT + text))
    else:  # 無 OCR 模型：擷取模型直接看圖；失敗時降解析度重試一次
        direct = EXTRACT_PROMPT.replace("掃描檔的 OCR 結果", "掃描影像（見附圖）").replace("\nOCR 結果：\n", "")
        try:
            x = check_answer(parse_json(call_llm(ext_st, direct, images)))
        except ValueError as e:
            log(f"重試（降解析度）{pdf.name}：{e}")
            low = render_pages(pdf, int(int(cfg["ocr"].get("dpi", 150)) * 0.67))
            x = check_answer(parse_json(call_llm(ext_st, direct, low)))
    v = None
    if ver_st.enabled:  # 複核失敗時降解析度重試一次，仍失敗則略過（不影響主結果）
        for attempt_dpi in (None, int(int(cfg["ocr"].get("dpi", 150)) * 0.67)):
            try:
                imgs = images if attempt_dpi is None else render_pages(pdf, attempt_dpi)
                v = parse_json(call_llm(ver_st, VERIFY_PROMPT, imgs))
                break
            except (RuntimeError, ValueError) as e:
                if attempt_dpi is not None:
                    log(f"複核略過 {pdf.name}：{str(e)[:80]}")
    row = build_row(x, v, cfg, pdf)
    if ver_st.enabled and v is None:
        row["備註"] = "；".join(filter(None, [row["備註"], "參考：複核模型未回應，本筆未經第二次比對"]))
    jdir = out / "json"  # 保存模型原始擷取結果，方便日後查核
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / f"{pdf.stem}.json").write_text(json.dumps({"擷取": x, "複核": v}, ensure_ascii=False, indent=1), encoding="utf-8")
    row.update({"來源檔案": str(pdf.relative_to(ROOT) if pdf.is_relative_to(ROOT) else pdf),
                "辨識時間": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
                "使用模型": " / ".join(s.model for s in (ocr_st, ext_st, ver_st) if s.enabled)})

    csv_dir.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():  # --force：舊檔先備份
        bak = csv_dir / "_backup"
        bak.mkdir(exist_ok=True)
        shutil.move(csv_path, bak / f"{pdf.stem}_{datetime.now():%Y%m%d_%H%M%S}.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerow(row)
    flag = f"，待確認：{row['待確認欄位']}" if row["待確認欄位"] else ""
    return f"完成 {pdf.name}（{time.time() - t0:.0f}s）{flag}"


def collect(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.suffix.lower() == ".pdf")
        elif p.suffix.lower() == ".pdf" and p.exists():
            out.append(p)
        else:
            log(f"找不到 PDF：{p}")
    return [q.resolve() for q in out]


def main() -> None:
    ap = argparse.ArgumentParser(description="核銷憑證 PDF → CSV")
    ap.add_argument("inputs", nargs="+", help="PDF 檔或資料夾")
    ap.add_argument("--force", action="store_true", help="已有 CSV 也重做（舊檔備份）")
    ap.add_argument("--reocr", action="store_true", help="連 OCR 文字都重跑")
    ap.add_argument("--config", type=Path, help="設定檔（預設 ocr_config.toml）")
    ap.add_argument("--out", type=Path, help="輸出資料夾（預設依設定檔）")
    ap.add_argument("--buyer-ubn", action="append", help="額外的本單位統編（可重複）")
    ap.add_argument("--buyer-name", action="append", help="額外的本單位全名（可重複）")
    ap.add_argument("--ocr-model", help="覆寫 [ocr] 模型；none = 不做整頁 OCR，直接看圖")
    ap.add_argument("--extract-model", help="覆寫 [extract] 擷取模型")
    ap.add_argument("--verify-model", help="覆寫 [verify] 複核模型；none = 不複核")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.buyer_ubn:
        cfg["org"]["buyer_ubns"] = list(cfg["org"]["buyer_ubns"]) + a.buyer_ubn
    if a.buyer_name:
        cfg["org"]["buyer_names"] = list(cfg["org"].get("buyer_names", [])) + a.buyer_name
    for sec, val in (("ocr", a.ocr_model), ("extract", a.extract_model), ("verify", a.verify_model)):
        if val is not None:
            cfg[sec]["model"] = "" if val.lower() in ("", "none") else val
    if not cfg["extract"]["model"]:
        raise SystemExit("必須指定擷取模型（[extract] model）")
    out = (a.out or ROOT / cfg["run"]["output_dir"]).resolve()
    pdfs = collect(a.inputs)
    log("模式：" + (f"{cfg['ocr']['model']} OCR → {cfg['extract']['model']}" if cfg["ocr"]["model"] else f"{cfg['extract']['model']} 直接看圖")
        + (f"，{cfg['verify']['model']} 複核" if cfg["verify"]["model"] else "，不複核"))
    log(f"共 {len(pdfs)} 個 PDF，輸出到 {out}")
    with ThreadPoolExecutor(max_workers=int(cfg["run"].get("concurrency", 2))) as ex:
        futs = {ex.submit(process, p, cfg, out, a.force, a.reocr): p for p in pdfs}
        for fu in as_completed(futs):
            try:
                log(fu.result())
            except Exception as e:  # 單一檔案失敗不影響其他檔案
                log(f"失敗 {futs[fu].name}：{e}")
    log("下一步：uv run .agents/skills/voucher-ocr/scripts/build_excel.py" + (f" --out {a.out}" if a.out else ""))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
