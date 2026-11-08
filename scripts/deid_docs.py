"""去識別化仿製：example/ 下五份核銷憑證 PDF。

不做遮罩，而是依原版面重新繪製整頁，所有可識別資訊改用虛構名稱、金額與代號；
每份文件使用不同的手寫風格（字型、筆色、粗細、傾斜、潦草程度）與掃描效果。
輸出純影像 PDF、預覽 PNG 與對應「自動立帳 spec.xlsx」欄位的標準答案 JSON。

執行：uv run scripts/deid_docs.py            （全部）
      uv run scripts/deid_docs.py 331 340    （指定文件）
"""

from __future__ import annotations

import math
import sys
from typing import Any, Callable

from PIL import Image, ImageDraw

from deid_common import (BLUE, BUYER_UBN, DIGITS, K, ORG1, ORG2, RED, HandStyle, P, Page, draw_uniform_invoice,
                         draw_voucher, font, money, save_outputs, scan_effect, stamp_layer, text_seal, tw_upper,
                         valid_ubn)

# ───────────────────────── 各文件手寫風格 ─────────────────────────
STYLES: dict[str, HandStyle] = {
    # 330：黑色原子筆、標楷＋Segoe Print，工整
    "330": HandStyle("kaiu.ttf", "segoepr.ttf", (30, 30, 45), rot=8, jitter=1.2),
    # 331：深藍簽字筆、方正舒體草寫＋Segoe Script，右傾
    "331": HandStyle("FZSTK.TTF", "segoesc.ttf", (25, 35, 95), rot=5, jitter=1.5, slant=0.25, size_var=0.15),
    # 340：紫藍原子筆、細楷＋Bradley Hand，潦草大小不一
    "340": HandStyle("STKAITI.TTF", "BRADHITC.TTF", (85, 70, 165), rot=11, jitter=2.0, size_var=0.2,
                     slant=0.12, tail="-", num_comma=True),
    # 341：藍色中性筆、方正姚體＋Ink Free，窄長、基線往上飄
    "341": HandStyle("FZYTK.TTF", "Inkfree.ttf", (35, 55, 150), rot=4, jitter=0.8, xscale=0.82,
                     drift=-0.25, num_comma=False, tail=""),
    # 350：黑色麥克筆、NaniFont 粗體＋Comic，粗筆畫
    "350": HandStyle("NaniFont-Regular.ttf", "comicbd.ttf", (20, 20, 25), rot=6, jitter=1.0, bold=3,
                     size_var=0.08, num_comma=False, tail="-"),
}


def seal(name: str, **kw: Any) -> dict[str, Any]:
    return {"k": "seal", "name": name, **kw}


def dated(top: str, date: str, name: str, **kw: Any) -> dict[str, Any]:
    return {"k": "dated", "top": top, "date": date, "name": name, **kw}


def sign(text: str, **kw: Any) -> dict[str, Any]:
    return {"k": "sign", "text": text, **kw}


AUDIT = "周雅婷"  # 會計審核（各文件共用）
CHIEF = "吳家豪"  # 主辦會計
HEAD = "鄭國華"  # 單位首長


def std_signers(audit_date: str, chief_date: str, handler: list, receiver: list, manager: list) -> list[list]:
    return [handler, receiver, manager, [],
            [dated("會　計", audit_date, AUDIT, dy=2)],
            [dated("主辦會計", chief_date, CHIEF, dx=-4, dy=16)],
            [{"k": "vseal", "name": HEAD}]]


# ───────────────────────── 330：三聯式統一發票 ─────────────────────────
def doc_330() -> tuple[Page, dict[str, Any], dict]:
    hs = STYLES["330"]
    net = 300_400
    tax, total = round(net * 0.05), round(net * 1.05)
    v = dict(total=total, print_date="2025/7/25 10:42:18", control_no="203114009187", receipt_no="3031114007712",
             purpose="114年度台中園區大樓清潔維護案_第三期款_DEMO-S-114052", tall_supplier=True,
             supplier="晴光環境清潔社", payee="晴光環境清潔社林志明", bank="(999)示範商業銀行", branch="(0101)中港分",
             account="880012345678", acct_code="03-1111-03114Z1500-0000-51330612-00-00",
             acct_desc="雲端中心\\-政府\\-補助\\-公務預算\\-當-03114Z1500_基本行政維持\\-其他費用-不分-清潔費-N/A-N/A",
             recv_date="114. 8.12", recv_date2="114. 7.31", made_voucher_stamp=True,
             signers=std_signers("114. 7.30", "114. 8. 5", [seal("陳立安", a=-2)], [seal("李宛如", a=1, dy=3)],
                                 [dated("核", "114. 7.28", "明哲", oval=True, w=44, h=40, dy=3)]))
    seller = dict(name="晴光環境清潔社", ubn="23831903", tel="0900123456", owner="林志明", addr="台中市示範區範例路一段100號")
    inv = dict(no="KX 52816403", period="一一四年七、八月份", period_short="7-8", roc_year="114", month="7", day="18",
               buyer_mode="hand", items=[("第三期請款費", 1, net, net)], net=net, tax=tax, total=total,
               seller=seller, note_seal="蔡宜真", item_size=13)
    pg = Page(330)
    draw_voucher(pg, v, hs)
    draw_uniform_invoice(pg, inv, hs)
    return pg, truth(v, inv["no"], total, seller["ubn"]), dict(rot=-0.35)


# ───────────────────────── 331：電子發票證明聯 ─────────────────────────
def draw_einvoice(pg: Page, e: dict[str, Any], hs: HandStyle) -> None:
    pg.dashed(36, 254, 375)
    pg.text(285, 378, "憑證黏貼線", 9, "msjhbd.ttc", anchor="ms")
    pg.dashed(316, 545, 375)
    pg.text(285, 440, "電子發票證明聯", 17, "msjhbd.ttc", anchor="ms")
    pg.text(285, 457, e["date"], 11, anchor="ms")
    pg.hand(432, 432, e["signer"], 17, hs)
    s = 10.5
    pg.text(36, 476, f"發票號碼：  {e['no']}", s)
    pg.text(36, 493, f"買　　方：  {ORG1}{ORG2}", s)
    end = 36 + pg.tlen(f"買　　方：  {ORG1}{ORG2}", s)
    pg.hand(end + 1, 494, "/", 12, hs)
    pg.text(36, 510, f"統一編號：  {BUYER_UBN}", s)
    pg.hand(36 + pg.tlen(f"統一編號：  {BUYER_UBN}", s) + 2, 511, "/", 12, hs)
    pg.text(36, 527, "地　　址：", s)
    pg.text(465, 496, f"格　式：{e['fmt']}", s)
    pg.text(465, 514, f"隨機碼：{e['rand']}", s)
    pg.text(545, 532, "第1頁/共1頁", s, anchor="rs")

    L, R = 16, 548
    ys = [535, 550, 578, 612, 655]
    for y in ys:
        pg.line(L, y, R, y)
    pg.line(L, ys[0], L, ys[-1])
    pg.line(R, ys[0], R, ys[-1])
    faded = (120, 120, 120)  # 表頭列印不清
    for x1, x2, t in ((16, 258, "品名"), (258, 311, "數量"), (311, 363, "單價"), (363, 432, "金額"), (432, 548, "備註")):
        pg.text((x1 + x2) / 2, 546, t, 9.5, fill=faded, anchor="ms")
        pg.line(x2, ys[0], x2, ys[1])
    pg.line(432, ys[1], 432, ys[-1])
    for x in (95, 144, 186, 236, 272, 324, 363):
        pg.line(x, ys[1], x, ys[2])
    pg.line(78, ys[3], 78, ys[4])
    pg.text(19, 568, "營業稅", s)
    pg.text(99, 568, "'應稅", s)
    pg.text(162, 568, "V", s)
    pg.text(190, 568, "零稅", s)
    pg.text(276, 568, "免稅", s)
    pg.text(429, 568, money(e["tax"]), s, anchor="rs")
    pg.text(19, 600, "總計", s)
    pg.text(429, 600, money(e["total"]), s, anchor="rs")
    pg.text(19, 630, "總計新臺幣", s)
    pg.text(19, 644, "(中文大寫)", s)
    pg.text(429, 640, tw_upper(e["total"])[3:-2] + " 元整", s, anchor="rs")
    sl = e["seller"]
    note = [f"賣方：{sl['name']}", f"統一編號：{sl['ubn']}", f"地址：{sl['addr'][:8]}", sl["addr"][8:]]
    for i, t in enumerate(note):
        pg.text(435, 561 + i * 13, t, 9.5)
    pg.hand(512, 562, "/", 10, hs)
    pg.hand(120, 572, "ˊ", 10, hs)
    pg.hand(120, 630, "ˊ", 10, hs)


def doc_331() -> tuple[Page, dict[str, Any], dict]:
    hs = STYLES["331"]
    net = 175_500
    tax, total = round(net * 0.05), round(net * 1.05)
    v = dict(total=total, print_date="2025/8/21 15:08:44", control_no="203114006142", receipt_no="3035114002291",
             purpose="文宣用影像素材庫圖檔授權採購", supplier="映川數位有限公司", payee="映川數位有限公司",
             bank="(998)範例商業銀行", branch="(0302)營業部", account="0451200098731",
             acct_code="03-1111-03114Z1600-0000-51331205-00-00",
             acct_desc="雲端中心\\-政府\\-補助\\-公務預算\\-當-03114Z1600_基本行政維持\\-企劃推廣及-不分-權利使用費-N/A-N/A",
             recv_date="114. 9. 2", recv_date2="114. 8.25", recv_x=552, recv_angle=-3,
             signers=std_signers("114. 8.25", "114. 8.29",
                                 [sign("許哲維", size=15)], [sign("高敏如", size=13, dx=4)],
                                 [seal("范振宇", w=32, h=14, dy=2)]),
             scribbles=[(98, 0, "哲維", 10), (165, -1, "敏如", 9), (228, 0, "振", 10)])
    seller = dict(name="映川數位有限公司", ubn="16480894", addr="台北市示範區範例東路五段88號12樓")
    e = dict(date="2025-08-19", signer="許哲維", no="QA48017256", fmt="25", rand="4826",
             tax=tax, total=total, seller=seller)
    pg = Page(331)
    draw_voucher(pg, v, hs)
    draw_einvoice(pg, e, hs)
    return pg, truth(v, e["no"], total, seller["ubn"]), dict(rot=0.25, blur=0.55, noise=0.03, staple=(10, 22, 30, 24))


# ───────────────────────── 340：免用發票收據 ─────────────────────────
def oval_receipt_seal(s: dict[str, str]) -> Any:
    m, d = stamp_layer(112, 80, BLUE)
    w, h = m.width, m.height
    d.ellipse((P(2), P(2), w - P(2), h - P(2)), outline=255, width=P(1.6))
    d.ellipse((P(22), P(18), w - P(22), h - P(18)), outline=255, width=P(1.1))
    # 外圈文字：上方店名、下方地址（逐字沿弧排列）
    def arc_text(t: str, start: float, end: float, r: float, size: float, bottom: bool = False) -> None:
        f = font("kaiu.ttf", size)
        n = len(t)
        for i, ch in enumerate(t):
            ang = math.radians(start + (end - start) * (i + 0.5) / n)
            x = w / 2 + r * K * 1.38 * math.cos(ang)
            y = h / 2 + r * K * math.sin(ang)
            tile = Image.new("L", (P(size * 1.4), P(size * 1.4)), 0)
            ImageDraw.Draw(tile).text((tile.width / 2, tile.height / 2), ch, font=f, fill=255, anchor="mm")
            rot = -math.degrees(ang) - 90 if not bottom else -math.degrees(ang) + 90
            tile = tile.rotate(rot, resample=Image.BICUBIC, expand=True)
            m.paste(255, (int(x - tile.width / 2), int(y - tile.height / 2)), tile)

    arc_text(s["name"], 205, 335, 31, 9.5)
    arc_text(s["addr"], 165, 15, 31, 6.5, bottom=True)
    for i, t in enumerate(("免用統一發票章", f"統編:{s['ubn']}", f"電話:{s['tel']}", s["owner"])):
        d.text((w / 2, P(28 + i * 8.5)), t, font=font("kaiu.ttf", 7.2), fill=255, anchor="mm")
    return m


def draw_receipt(pg: Page, r: dict[str, Any], hs: HandStyle, dy: float = 0, header: bool = True) -> None:
    """免用發票收據一張；dy 用於繪製被上一張遮住的第二張。"""
    C = (60, 60, 70)
    if header:
        pg.text(347, 397 + dy, "中華民國", 9.5, "kaiu.ttf", C)
        pg.hand(384, 399 + dy, r["roc_year"], 13, hs)
        pg.text(416, 397 + dy, "年", 9.5, "kaiu.ttf", C)
        pg.hand(424, 399 + dy, r["month"], 15, hs)
        pg.text(444, 397 + dy, "月", 9.5, "kaiu.ttf", C)
        pg.hand(456, 399 + dy, r["day"], 14, hs)
        pg.text(480, 397 + dy, "日", 9.5, "kaiu.ttf", C)
        pg.text(245, 418 + dy, "免用發票收據", 17, "kaiu.ttf", C, anchor="ms")
        pg.line(185, 422 + dy, 306, 422 + dy, C, 0.9)
        pg.text(327, 427 + dy, "統一編號：", 8.5, "kaiu.ttf", C)
        for i, c in enumerate(BUYER_UBN):
            x = 372 + i * 16
            pg.rect(x, 413 + dy, x + 16, 430 + dy, C, 0.6)
            pg.hand(x + 2, 428 + dy, c, 14, hs)
        pg.text(111, 444 + dy, "買受人", 7.5, "kaiu.ttf", C)
        pg.text(316, 441 + dy, "地址", 6, "kaiu.ttf", C)
        pg.hand(126, 447 + dy, ORG1 + ORG2, 12.5, hs, gap=-1.5)
    L, R = 110, 501
    cols = [L, 219, 262, 308, 370, R]
    ys = [451, 470, 491, 513, 535, 556, 578, 600, 622, 648]
    ys = [y + dy for y in ys]
    pg.rect(L, ys[0], R, ys[-1], C, 0.8)
    for y in ys[1:-1]:
        pg.line(L, y, 370, y, C, 0.6)
    pg.line(370, ys[1], R, ys[1], C, 0.6)
    pg.line(370, ys[-2], R, ys[-2], C, 0.6)
    for x in cols[1:-1]:
        pg.line(x, ys[0], x, ys[-2], C, 0.6)
    pg.line(370, ys[-2], 370, ys[-1], C, 0.6)
    for x in (288, 349):
        pg.vdotted(x, ys[1], ys[-2], C)
    for x, t in ((164, "摘　　要"), (240, "數　量"), (285, "單　價"), (339, "總　價"), (435, "備　　　　註")):
        pg.text(x, ys[0] + 13, t, 8.5, "kaiu.ttf", C, anchor="ms")
    pg.text(115, ys[-1] - 7, "合計新台幣", 8, "kaiu.ttf", C)
    units = [(190, "萬"), (239, "千"), (285, "百"), (324, "拾"), (360, "元"), (407, "角")]
    for x, u in units:
        pg.text(x, ys[-1] - 7, u, 8, "kaiu.ttf", C)
    pg.line(160, ys[-1] - 5, 368, ys[-1] - 5, C, 0.4)
    if header:
        pg.text(435, ys[1] + 17, "收 據 專 用 章", 8.5, "kaiu.ttf", C, anchor="ms", spacing=0)

    for i, (name, qty, price, amt) in enumerate(r["items"]):
        yb = ys[i + 2] - 4
        pg.hand(114, yb, name, 15, hs, gap=-1.0)
        pg.hand(236, yb, str(qty), 13, hs)
        pg.hand(268, yb, f"{price}" + hs.tail, 11, hs)
        pg.hand(318, yb, f"{amt}" + hs.tail, 12, hs)
    n = len(r["items"])
    total = sum(a for *_, a in r["items"])
    if n < 6:
        pg.line(331, ys[n + 1] + 4, 328, ys[-3] - 3, hs.color, 1.0)
    pg.hand(318, ys[-2] - 4, f"{total}" + "/", 12, hs)
    s = str(total)
    for (x, _), c in zip(units[5 - len(s):5], s):
        pg.hand(x - 15, ys[-1] - 3, DIGITS[int(c)], 15, hs)
    pg.stamp(435, ys[-2] - 6, text_seal("銀貨兩訖", (30, 30, 30), 58, 20, 11.5), -1, 0.9)
    pg.stamp(484, ys[-2] - 6, text_seal(r["seller"]["name"][:2] + "\n" + r["seller"]["name"][2:4], RED, 22, 24, 8), 0, 0.85)
    pg.stamp(436, ys[0] + 100, oval_receipt_seal(r["seller"]), -18, 0.85)


def doc_340() -> tuple[Page, dict[str, Any], dict]:
    hs = STYLES["340"]
    seller = dict(name="長興企業社", ubn="17784483", tel="03-5550186", owner="許文堂", addr="新竹市示範路一段131號")
    r1 = dict(roc_year="114", month="8", day="20", seller=seller,
              items=[("連續章", 8, 80, 640), ("自動日期章", 3, 260, 780), ("原子印章", 2, 350, 700),
                     ("配製鑰匙", 1, 250, 250), ("修理門鎖", 1, 120, 120)])
    r2 = dict(r1, items=[("鑰匙圈", 4, 190, 760)])
    total = sum(a for *_, a in r1["items"]) + sum(a for *_, a in r2["items"])
    v = dict(total=total, print_date="2025/8/27 14:31:09", control_no="203114007326", receipt_no="3031114005518",
             purpose="114年下半年刻印及配鎖費用", supplier="長興企業社", payee="長興企業社",
             bank="(997)示例商業銀行", branch="(0218)科園分行", account="077120034519",
             acct_code="03-1111-03114Z1500-0000-51330688-00-00",
             acct_desc="雲端中心\\-政府\\-補助\\-公務預算\\-當-03114Z1500_基本行政維持\\-其他費用-不分-其它一般事務費-N/A-N/A",
             recv_date="114. 9. 9", recv_date2="114. 8.28",
             signers=std_signers("114. 8.29", "114. 9. 3",
                                 [seal("陳立安", dx=-10, a=-1), sign("114.", size=9, dx=24, dy=-6), sign("08.21", size=9, dx=26, dy=6)],
                                 [], [dated("何", "114. 8.22", "佳蓉", oval=True, w=44, h=40, dy=3)]))
    pg = Page(340)
    draw_voucher(pg, v, hs)
    pg.dashed(36, 254, 375)
    pg.text(285, 378, "憑證黏貼線", 9, "msjhbd.ttc", anchor="ms")
    pg.dashed(316, 545, 375)
    draw_receipt(pg, r2, hs, dy=103, header=False)  # 第二張（被第一張蓋住上半）
    pg.white(104, 388, 508, 655)
    draw_receipt(pg, r1, hs)
    return pg, truth(v, "收據", total, seller["ubn"]), dict(rot=0.5, blur=0.8, noise=0.05, paper=(248, 246, 240), staple=(12, 22, 30, 21))


# ───────────────────────── 341：三聯式（含折讓列、第三聯） ─────────────────────────
def doc_341() -> tuple[Page, dict[str, Any], dict]:
    hs = STYLES["341"]
    items = [("簡報室壓克力招牌H15cm", 1, 5200, 5200), ("拆除舊招牌及施工", 1, 3500, 3500), ("優惠", 1, None, -605)]
    net = sum(a for *_, a in items)
    total = 8_500
    tax = total - net
    v = dict(total=total, print_date="2025/9/3 09:21:37", control_no="203114008054", receipt_no="3033114001146",
             purpose="台中園區簡報室招牌更新", tall_supplier=True, supplier="瑞峰企業有限公司", payee="瑞峰企業有限公司",
             bank="(996)樣本信用合作社", branch="(0157)西", branch_wrap="屯分社", account="01570030000288",
             acct_code="03-1111-03114Z1500-0000-51320104-00-00",
             acct_desc="雲端中心\\-政府\\-補助\\-公務預算\\-當-03114Z1500_基本行政維持\\-其他費用-不分-房屋建築修繕費-N/A-N/A",
             recv_date="114. 9.15", recv_date2="114. 9. 5",
             signers=std_signers("114. 9. 5", "114. 9.10", [seal("賴文傑", w=34, h=15, color=(215, 90, 110))], [],
                                 [dated("蘇", "114. 9. 4", "品妍", oval=True, w=44, h=40, dy=3)]),
             scribbles=[(98, 0, "OK", 8)])
    seller = dict(name="瑞峰企業有限公司", ubn="18302983", tel="04-25550913", owner="洪啟明", addr="台中市示範區中港路二段88號1F")
    inv = dict(no="PM 63950418", period="一一四年七、八月份", period_short="7-8", roc_year="114", month="8", day="27",
               buyer_mode="hand2", items=items, net=net, tax=tax, total=total, seller=seller, note_seal="蔡宜真",
               item_size=10.5, item_gap=-1.6, third_copy=True, seal_angle=-3)
    pg = Page(341)
    draw_voucher(pg, v, hs)
    draw_uniform_invoice(pg, inv, hs)
    return pg, truth(v, inv["no"], total, seller["ubn"]), dict(rot=-0.6, blur=0.65, noise=0.035, staple=(12, 22, 32, 18))


# ───────────────────────── 350：三聯式（抬頭蓋章、麥克筆） ─────────────────────────
def doc_350() -> tuple[Page, dict[str, Any], dict]:
    hs = STYLES["350"]
    items = [("傳票封面", 1200, 32, 38400), ("黏存單", 800, 36, 28800)]
    net = sum(a for *_, a in items)
    tax, total = round(net * 0.05), round(net * 1.05)
    v = dict(total=total, print_date="2025/9/10 09:13:55", control_no="203114008611", receipt_no="3031114005930",
             purpose="印製會計傳票封面及黏存單", tall_supplier=True, supplier="全興專業印刷有限公司",
             payee="全興專業印刷有限公司", bank="(995)測試商業銀行", branch="(0299)新竹分", account="377208061945",
             acct_code="03-1111-03114Z1500-0000-51330605-00-00",
             acct_desc="雲端中心\\-政府\\-補助\\-公務預算\\-當-03114Z1500_基本行政維持\\-其他費用-不分-印刷及裝訂費-N/A-N/A",
             recv_date="114. 9.19", recv_date2="114. 9.12", recv_x=550, recv_angle=8,
             signers=std_signers("114. 9.16", "114. 9.16", [seal("孫慧君", w=32, h=14)], [seal("方若琳", w=32, h=14, dy=-3)], []),
             scribbles=[(48, 0, "慧君", 8.5), (115, 0, "若琳", 8.5), (196, 0, "品欣", 8.5)])
    seller = dict(name="全興專業印刷有限公司", ubn="95753514", tel="(03)5550421", owner="葉建宏", addr="新竹市示範路二段146號1樓")
    inv = dict(no="WD 30627719", period="一一四年九、十月份", period_short="9-10", roc_year="114", month="9", day="5",
               buyer_mode="stamp", items=items, net=net, tax=tax, total=total, seller=seller, note_seal=None,
               item_size=13, item_gap=-0.5, third_copy=True, seal_angle=2)
    pg = Page(350)
    draw_voucher(pg, v, hs)
    draw_uniform_invoice(pg, inv, hs)
    return pg, truth(v, inv["no"], total, seller["ubn"]), dict(rot=0.3, blur=0.75, noise=0.045, paper=(251, 250, 247), staple=(10, 20, 26, 19))


def truth(v: dict[str, Any], inv_no: str, amount: int, seller_ubn: str) -> dict[str, Any]:
    """對應「自動立帳 spec.xlsx」欄位的標準答案。"""
    if seller_ubn and not valid_ubn(seller_ubn):
        raise SystemExit(f"賣方統編檢查碼不合法：{seller_ubn}")
    return {"會計科目": v["acct_code"], "控帳編號": v["control_no"], "發票號碼": inv_no.replace(" ", ""),
            "發票金額": amount, "總計金額": v["total"], "發票統編": seller_ubn, "發票抬頭": ORG1 + ORG2,
            "收貨單號": v["receipt_no"], "核銷金額大寫": tw_upper(v["total"]), "供應商": v["supplier"]}


DOCS: dict[str, Callable[[], tuple[Page, dict[str, Any], dict]]] = {
    "330": doc_330, "331": doc_331, "340": doc_340, "341": doc_341, "350": doc_350,
}


def main(keys: list[str]) -> None:
    if not valid_ubn(BUYER_UBN):
        raise SystemExit("買方統編檢查碼不合法")
    for k in keys or list(DOCS):
        try:
            pg, t, scan = DOCS[k]()
            img = scan_effect(pg.img, int(k), **scan)
            print("已輸出：", save_outputs(img, f"SKM_650i25101515{k}_deid", t))
        except KeyError:
            print(f"未知文件代號：{k}（可用：{', '.join(DOCS)}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
