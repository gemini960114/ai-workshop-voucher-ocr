"""去識別化仿製：共用繪圖元件（頁面、手寫風格、印章、核銷憑證黏存單、三聯式發票、掃描效果）。"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DPI = 200
K = DPI / 72  # pt → px
W, H = round(595.2 * K), round(841.68 * K)
OUT_DIR = Path("example_deid")

FONT_DIRS = [Path("C:/Windows/Fonts"), Path(os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts"))]
INK = (25, 25, 35)  # 印刷黑
INV = (80, 80, 165)  # 發票紫藍
RED_FORM = (200, 60, 70)  # 收執聯紅色印刷
RED = (205, 45, 55)
BLUE = (45, 65, 175)

# 虛構機關（所有文件共用，作為發票抬頭）
ORG1 = "財團法人未來科技研究院"
ORG2 = "智慧雲端運算中心"
ORG_SHORT = "雲端中心"
BUYER_UBN = "81924865"


def P(v: float) -> int:
    return round(v * K)


@lru_cache(maxsize=None)
def font_path(name: str) -> str:
    for d in FONT_DIRS:
        if (d / name).exists():
            return str(d / name)
    raise SystemExit(f"找不到字型：{name}")


@lru_cache(maxsize=None)
def font_px(name: str, px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path(name), max(px, 1))
    except OSError as e:
        raise SystemExit(f"字型載入失敗 {name}：{e}") from e


def font(name: str, size_pt: float) -> ImageFont.FreeTypeFont:
    """載入字型（size 以 pt 計）。"""
    return font_px(name, round(size_pt * K))


@lru_cache(maxsize=None)
def has_glyph(name: str, ch: str) -> bool:
    """以「與缺字框比對」判斷字型是否含此字。"""
    f = font_px(name, 40)
    notdef = f.getmask("\U0010fffd")
    m = f.getmask(ch)
    return not (m.size == notdef.size and bytes(m) == bytes(notdef))


def money(n: int) -> str:
    return f"{n:,}"


DIGITS = "零壹貳參肆伍陸柒捌玖"


def tw_upper(n: int) -> str:
    """整數轉中文大寫金額（新台幣…元整）。"""
    units = ["", "拾", "佰", "仟"]
    out, zero = "", False
    for big, name in ((n // 10_000, "萬"), (n % 10_000, "")):
        if big == 0:
            continue
        s = str(big).zfill(4) if out else str(big)
        for i, c in enumerate(s):
            u = units[len(s) - 1 - i]
            if c == "0":
                zero = bool(out)
            else:
                if zero:
                    out += "零"
                    zero = False
                out += DIGITS[int(c)] + u
        out += name
    return f"新台幣{out}元整"


def valid_ubn(s: str) -> bool:
    """統一編號檢查碼驗證（財政部新制，總和可被 5 整除）。"""
    w = [1, 2, 1, 2, 1, 2, 4, 1]
    t = sum(sum(divmod(int(c) * k, 10)) for c, k in zip(s, w))
    return t % 5 == 0 or (s[6] == "7" and (t + 1) % 5 == 0)


@dataclass
class HandStyle:
    """手寫風格：字型、墨色、筆畫粗細、傾斜、壓縮、抖動、基線漂移。"""

    cjk: str
    latin: str
    color: tuple[int, int, int]
    scale: float = 1.0
    size_var: float = 0.1
    rot: float = 8.0  # 單字最大旋轉角度
    jitter: float = 1.0  # 上下位移（pt）
    slant: float = 0.0  # 斜體剪切係數（正值右傾）
    xscale: float = 1.0  # 水平壓縮
    bold: int = 0  # 筆畫加粗（MaxFilter 尺寸，奇數）
    gap: float = 0.0  # 字距修正（pt）
    drift: float = 0.0  # 每字基線漂移（pt，負值往上）
    num_comma: bool = True
    tail: str = "—"  # 金額結尾記號


class Page:
    """以 pt 座標繪製的頁面。"""

    def __init__(self, seed: int) -> None:
        self.img = Image.new("RGB", (W, H), (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)
        self.rng = random.Random(seed)

    def text(self, x: float, y: float, s: str, size: float, fname: str = "msjh.ttc",
             fill: tuple[int, int, int] = INK, anchor: str = "ls", spacing: float = 0) -> None:
        f = font(fname, size)
        if spacing:
            cx = x
            for ch in s:
                self.d.text((P(cx), P(y)), ch, font=f, fill=fill, anchor=anchor)
                cx += f.getlength(ch) / K + spacing
        else:
            self.d.text((P(x), P(y)), s, font=f, fill=fill, anchor=anchor)

    def tlen(self, s: str, size: float, fname: str = "msjh.ttc") -> float:
        return font(fname, size).getlength(s) / K

    def line(self, x1: float, y1: float, x2: float, y2: float, fill=INK, w: float = 0.8) -> None:
        self.d.line((P(x1), P(y1), P(x2), P(y2)), fill=fill, width=max(1, P(w)))

    def rect(self, x1: float, y1: float, x2: float, y2: float, fill=INK, w: float = 0.8) -> None:
        self.d.rectangle((P(x1), P(y1), P(x2), P(y2)), outline=fill, width=max(1, P(w)))

    def white(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.d.rectangle((P(x1), P(y1), P(x2), P(y2)), fill=(255, 255, 255))

    def dashed(self, x1: float, x2: float, y: float, fill=INK, dash: float = 2.2, step: float = 3.6) -> None:
        x = x1
        while x < x2:
            self.line(x, y, min(x + dash, x2), y, fill, 0.6)
            x += step

    def vdotted(self, x: float, y1: float, y2: float, fill=INV) -> None:
        y = y1
        while y < y2:
            self.line(x, y, x, min(y + 1.2, y2), fill, 0.5)
            y += 2.6

    def hand(self, x: float, y: float, s: str, size: float, hs: HandStyle,
             gap: float = 0.0, color: tuple[int, int, int] | None = None) -> float:
        """依手寫風格逐字繪製（隨機位移、旋轉、縮放、傾斜、加粗）。回傳結束 x。"""
        rng, cx, drift = self.rng, x, 0.0
        fill = color or hs.color
        for ch in s:
            if ch == " ":
                cx += size * 0.35
                continue
            fname = hs.latin if ord(ch) < 128 else hs.cjk
            if ch in "✓":
                fname = "seguisym.ttf"
            elif not has_glyph(fname, ch):
                fname = "kaiu.ttf"
            sz = size * hs.scale * rng.uniform(1 - hs.size_var, 1 + hs.size_var)
            f = font(fname, sz)
            adv = f.getlength(ch)
            tile = Image.new("L", (int(adv) + P(6), P(sz * 1.6)), 0)
            ImageDraw.Draw(tile).text((P(3), P(sz * 1.2)), ch, font=f, fill=255, anchor="ls")
            if hs.bold:
                tile = tile.filter(ImageFilter.MaxFilter(hs.bold))
            if hs.xscale != 1:
                tile = tile.resize((max(1, int(tile.width * hs.xscale)), tile.height), Image.BICUBIC)
            if hs.slant:
                k, h = hs.slant, tile.height
                tile = tile.transform((tile.width + int(abs(k) * h), h), Image.AFFINE,
                                      (1, k, -k * h if k > 0 else 0, 0, 1, 0), Image.BICUBIC)
            tile = tile.rotate(rng.uniform(-hs.rot, hs.rot), resample=Image.BICUBIC, expand=True)
            px = P(cx) + rng.randint(-2, 2)
            py = P(y - sz * 1.2 + drift) + int(rng.uniform(-hs.jitter, hs.jitter) * K)
            self.img.paste(Image.new("RGB", tile.size, fill), (px, py), tile)
            cx += adv * hs.xscale / K + gap + hs.gap + rng.uniform(-0.5, 0.7)
            drift += hs.drift
        return cx

    def hnum(self, x: float, y: float, n: int, size: float, hs: HandStyle, tail: bool = True, align_right: float | None = None) -> None:
        """手寫金額。"""
        s = (f"{n:,}" if hs.num_comma else str(n)) + (hs.tail if tail else "")
        if align_right is not None:
            x = align_right - len(s) * size * 0.5 * hs.xscale
        self.hand(x, y, s, size, hs)

    def stamp(self, cx: float, cy: float, layer: Image.Image, angle: float, alpha: float = 0.85) -> None:
        """把印章遮罩旋轉後疊上，帶不均勻墨色。"""
        color = layer.info["color"]
        mask = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
        noise = Image.effect_noise(mask.size, 60).point(lambda v: 255 if v > 70 else 120)
        mask = Image.composite(mask, Image.new("L", mask.size, 0), noise)
        mask = mask.point(lambda v: int(v * alpha))
        x, y = P(cx) - mask.width // 2, P(cy) - mask.height // 2
        self.img.paste(Image.new("RGB", mask.size, color), (x, y), mask)


# ───────────────────────── 印章 ─────────────────────────
def stamp_layer(w: float, h: float, color: tuple[int, int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    m = Image.new("L", (P(w), P(h)), 0)
    m.info["color"] = color
    return m, ImageDraw.Draw(m)


def name_seal(name: str, color=RED, w: float = 36, h: float = 15, fname: str = "kaiu.ttf") -> Image.Image:
    """長方形姓名章。"""
    m, d = stamp_layer(w, h, color)
    d.rectangle((0, 0, m.width - 1, m.height - 1), outline=255, width=P(1.6))
    d.text((m.width / 2, m.height / 2), name, font=font(fname, h - 5), fill=255, anchor="mm")
    return m


def vertical_seal(name: str, caption: str = "核銷專用章(甲)", color=RED, w: float = 34, h: float = 42) -> Image.Image:
    """兩欄直書職章（右欄先讀），下附小字。"""
    m, d = stamp_layer(w, h, color)
    d.rectangle((0, 0, m.width - 1, P(h - 8)), outline=255, width=P(1.4))
    chars = list(name[1:]) if len(name) == 3 else list(name)
    cols = [[name[0]], chars] if len(name) == 3 else [chars[:1], chars[1:]]
    f = font("kaiu.ttf", (w - 8) / 2 + 1)
    cw = m.width / 2
    for i, col in enumerate(reversed(cols)):  # 左欄放後兩字
        for j, ch in enumerate(col):
            yy = P(h - 8) * (j + 0.5) / len(col)
            d.text((cw * (i + 0.5), yy), ch, font=f, fill=255, anchor="mm")
    d.rectangle((0, P(h - 7), m.width - 1, m.height - 1), outline=255, width=P(0.8))
    d.text((m.width / 2, P(h - 3.5)), caption, font=font("kaiu.ttf", 5), fill=255, anchor="mm")
    return m


def dated_seal(top: str, date: str, bottom: str, color=RED, w: float = 46, h: float = 32, oval: bool = False) -> Image.Image:
    """三段式日期章（上：單位／中：日期／下：姓名）。"""
    m, d = stamp_layer(w, h, color)
    box = (1, 1, m.width - 2, m.height - 2)
    (d.ellipse if oval else d.rectangle)(box, outline=255, width=P(1.3))
    if not oval:
        d.line((0, m.height * 0.35, m.width, m.height * 0.35), fill=255, width=P(0.9))
        d.line((0, m.height * 0.62, m.width, m.height * 0.62), fill=255, width=P(0.9))
    d.text((m.width / 2, m.height * 0.19), top, font=font("kaiu.ttf", h * 0.22), fill=255, anchor="mm")
    d.text((m.width / 2, m.height * 0.49), date, font=font("msjh.ttc", h * 0.2), fill=255, anchor="mm")
    d.text((m.width / 2, m.height * 0.80), bottom, font=font("kaiu.ttf", h * 0.26), fill=255, anchor="mm")
    return m


def text_seal(text: str, color, w: float, h: float, size: float, frame: bool = True, fname: str = "kaiu.ttf") -> Image.Image:
    m, d = stamp_layer(w, h, color)
    if frame:
        d.rectangle((0, 0, m.width - 1, m.height - 1), outline=255, width=P(1.4))
    d.multiline_text((m.width / 2, m.height / 2), text, font=font(fname, size), fill=255, anchor="mm", align="center", spacing=P(1))
    return m


def invoice_seal(s: dict[str, str]) -> Image.Image:
    """營業人統一發票專用章（上下弧形外框）。"""
    m, d = stamp_layer(118, 88, BLUE)
    wpx, hpx, lw = m.width, m.height, P(1.6)
    d.arc((P(2), P(2), wpx - P(2), P(34)), 180, 360, fill=255, width=lw)
    d.arc((P(2), hpx - P(34), wpx - P(2), hpx - P(2)), 0, 180, fill=255, width=lw)
    d.line((P(2), P(18), P(2), hpx - P(18)), fill=255, width=lw)
    d.line((wpx - P(3), P(18), wpx - P(3), hpx - P(18)), fill=255, width=lw)
    flower = font("seguisym.ttf", 9)
    d.text((P(10), P(52)), "✿", font=flower, fill=255, anchor="mm")
    d.text((wpx - P(10), P(52)), "✿", font=flower, fill=255, anchor="mm")
    d.text((wpx / 2, P(13)), s["name"], font=font("kaiu.ttf", 11.5 if len(s["name"]) <= 7 else 9.5), fill=255, anchor="mm")
    d.text((wpx / 2, P(28)), "統一發票專用章", font=font("kaiu.ttf", 9), fill=255, anchor="mm")
    d.text((wpx / 2, P(39)), "統一編號", font=font("kaiu.ttf", 8.5), fill=255, anchor="mm")
    d.text((wpx / 2, P(52)), s["ubn"], font=font("arialbd.ttf", 14), fill=255, anchor="mm")
    d.text((wpx / 2, P(63)), f"TEL:{s['tel']}", font=font("timesbd.ttf", 9), fill=255, anchor="mm")
    d.text((wpx / 2, P(72.5)), f"負責人:{s['owner']}", font=font("kaiu.ttf", 8.5), fill=255, anchor="mm")
    d.text((wpx / 2, P(81)), s["addr"], font=font("msjhbd.ttc", 6.8 if len(s["addr"]) <= 14 else 5.6), fill=255, anchor="mm")
    return m


# ───────────────────────── 核銷憑證黏存單 ─────────────────────────
def wrap(s: str, size: float, max_w: float, fname: str = "msjh.ttc") -> list[str]:
    f, out, cur = font(fname, size), [], ""
    for ch in s:
        if f.getlength(cur + ch) / K > max_w:
            out.append(cur)
            cur = ""
        cur += ch
    return out + [cur]


def draw_voucher(pg: Page, v: dict[str, Any], hs: HandStyle) -> float:
    """上半部：核銷憑證黏存單。回傳簽核欄底部 y。"""
    total = v["total"]
    pg.text(390, 56, f"印表日期：{v['print_date']}", 10.5)
    for i, t in enumerate((ORG1, ORG2, "核銷憑證黏存單")):
        pg.text(295, 72 + i * 20, t, 13.5, "msjhbd.ttc", anchor="ms")
    pg.text(390, 117, "頁　 次：第 1 頁，共 1 頁", 9.5)
    pg.text(390, 130, f"收貨單號：{v['receipt_no']}", 9.5)
    pg.text(40, 125, f"控帳編號：{v['control_no']}", 9.5)

    tall = v.get("tall_supplier", False)
    hs_rows = [18, 16, 16, 48, 16, 14, 39, 13, 16, 49] if tall else [20, 18, 18, 18, 18, 17, 52, 14, 18, 48]
    ys = [131.0]
    for h in hs_rows:
        ys.append(ys[-1] + h)
    L, R, s = 36, 545, 10.5
    for y in ys:
        pg.line(L, y, R, y, w=0.5 if y == ys[7] else 0.8)
    pg.line(L, ys[0], L, ys[-1])
    pg.line(R, ys[0], R, ys[-1])
    b = [y - 4.5 for y in ys[1:]]  # 各列文字基線

    pg.text(40, b[0], "憑證編號：", s)
    pg.line(135, ys[0], 135, ys[1])
    pg.text(140, b[0], f"核銷金額：{tw_upper(total)}(${money(total)})", s)
    pg.text(40, b[1], f"用途說明：{v['purpose']}", s)
    pg.text(40, b[2], "付款方式：逕匯入帳", s)
    pg.line(232, ys[2], 232, ys[3])
    pg.text(236, b[2], "沖銷暫借款單號：", s)
    pg.line(403, ys[2], 403, ys[3])
    pg.text(415, b[2], "領款人：", s)
    sup_y = ys[3] + 13 if tall else b[3]
    pg.text(40, sup_y, f"供 應 商：  {v['supplier']}/{ORG_SHORT}", s)
    pg.line(290, ys[3], 290, ys[5])
    pg.text(294, sup_y, f"行庫：  {v['bank']}", s)
    if tall:
        pg.text(475, sup_y, v["branch"], s)
        pg.text(340, sup_y + 14, v.get("branch_wrap", "行"), s)
    else:
        pg.text(294 + pg.tlen(f"行庫：  {v['bank']} ", s), sup_y, v["branch"], s)
    pg.text(40, b[4], f"戶　 名：  {v['payee']}", s)
    pg.text(294, b[4], f"帳號：  {v['account']}", s)
    pg.line(483, ys[5], 483, ys[8])
    pg.text(259, b[5], "會 計 科 目 / 科 目 說 明", s, "msjhbd.ttc", anchor="ms")
    pg.text(514, b[5], "金　 額", s, "msjhbd.ttc", anchor="ms")
    ih = hs_rows[6]
    pg.text(61, ys[6] + ih * 0.32, v["acct_code"], s)
    pg.text(44, ys[6] + ih * 0.66, "1", s)
    for i, ln in enumerate(wrap(v["acct_desc"], s, 418)[:2]):
        pg.text(61, ys[6] + ih * (0.66 + 0.32 * i), ln, s)
    pg.text(541, ys[6] + ih * 0.66, f"${money(total)}", s, anchor="rs")
    pg.text(250, b[7] + 1.5, "總　　　　　計", s, "msjhbd.ttc", anchor="ms")
    pg.text(541, b[7] + 1.5, f"${money(total)}", s, anchor="rs")
    cols = [36, 98, 175, 252, 327, 402, 480, 545]
    heads = ["經手人", "協驗或驗收人", "權責主管", "會核單位", "會計審核", "會計主管", "單位首長"]
    for x in cols[1:-1]:
        pg.line(x, ys[8], x, ys[10])
    for i, h in enumerate(heads):
        pg.text((cols[i] + cols[i + 1]) / 2, b[8], h, s, "msjhbd.ttc", anchor="ms")

    # 頁首章
    if v.get("made_voucher_stamp"):
        m, d = stamp_layer(116, 26, RED)
        d.rectangle((0, 0, m.width - 1, m.height - 1), outline=255, width=P(1.5))
        d.text((m.width / 2, m.height / 2), "已 製 傳 票", font=font("kaiu.ttf", 19), fill=255, anchor="mm")
        pg.stamp(103, 81, m, 4)
    pg.stamp(v.get("recv_x", 553), 100, dated_seal("財會組", v["recv_date"], "收文章", BLUE, 42, 40), v.get("recv_angle", 0), 0.9)
    pg.stamp(398, ys[7] - 9, dated_seal("財會組", v["recv_date2"], "收文章", BLUE, 40, 34), 2, 0.75)

    # 簽核欄
    top = ys[9]
    for i, cell in enumerate(v["signers"]):
        cx = (cols[i] + cols[i + 1]) / 2
        cy = top + 22
        for e in cell:
            x, y = cx + e.get("dx", 0), cy + e.get("dy", 0)
            k = e["k"]
            if k == "seal":
                pg.stamp(x, y, name_seal(e["name"], e.get("color", RED), e.get("w", 36), e.get("h", 15)), e.get("a", 0))
            elif k == "vseal":
                pg.stamp(x, y, vertical_seal(e["name"]), e.get("a", 1))
            elif k == "dated":
                pg.stamp(x, y, dated_seal(e["top"], e["date"], e["name"], RED, e.get("w", 46), e.get("h", 34), e.get("oval", False)), e.get("a", 0))
            elif k == "sign":
                pg.hand(x - e.get("size", 14) * len(e["text"]) * 0.45, y + 5, e["text"], e.get("size", 14), e.get("hs", hs))
    for x, dy, t, sz in v.get("scribbles", []):  # 簽核時隨手寫在總計列的字
        pg.hand(x, ys[8] - 1 + dy, t, sz, hs)
    return ys[-1]


# ───────────────────────── 三聯式統一發票 ─────────────────────────
UNIT_X = [128, 157, 186, 215, 244, 273, 302, 331, 360]


def daxie_row(pg: Page, y1: float, y2: float, color, hs: HandStyle, total: int, carbon: bool = False) -> None:
    """總計新臺幣（中文大寫）列：前導位數劃線，其餘填大寫數字。"""
    pg.rect(72, y1, 357, y2, color, 0.8)
    pg.text(74, y1 + 6.5, "總計新臺幣", 6.5, "mingliu.ttc", color)
    pg.text(74, y1 + 14, "(中文大寫)", 6.5, "mingliu.ttc", color)
    for x, u in zip(UNIT_X, "億仟佰拾萬仟佰拾元"):
        pg.text(x, y2 - 4, u, 8.5, "mingliu.ttc", color)
    s = str(total)
    lead = 9 - len(s)
    col = tuple(min(255, c + 40) for c in hs.color) if carbon else None
    if lead:
        pg.line(UNIT_X[0] - 40, y2 - 7, UNIT_X[lead - 1] + 8, y2 - 8.5, col or hs.color, 1.1)
    for x, c in zip(UNIT_X[lead:], s):
        pg.hand(x - 15, y2 - 2, DIGITS[int(c)], 13.5, hs, gap=-1, color=col)


def draw_uniform_invoice(pg: Page, inv: dict[str, Any], hs: HandStyle) -> None:
    """下半部：三聯式統一發票（第二聯扣抵聯，可選帶出第三聯收執聯下緣）。"""
    pg.dashed(36, 196, 382)
    pg.text(248, 385, "憑證黏貼線", 9, "msjhbd.ttc", anchor="ms")
    pg.dashed(300, 560, 382)
    C = INV
    pg.text(72, 402, inv["no"], 12.5, "consola.ttf", C)
    pg.text(190, 401, "統　　　發　　　票（三聯式）", 12, "mingliu.ttc", C)
    pg.text(214, 401, "一", 12, "mingliu.ttc", C)
    pg.text(290, 418, inv["period"], 10.5, "mingliu.ttc", C, anchor="ms", spacing=1.2)
    pg.rect(408, 389, 487, 460, C, 0.7)
    pg.text(447, 400, "買受人註記欄", 6.5, "mingliu.ttc", C, anchor="ms")
    pg.line(408, 404, 487, 404, C, 0.5)
    for x in (430, 459):
        pg.line(x, 404, x, 460, C, 0.5)
    pg.line(408, 432, 487, 432, C, 0.5)
    for x, y, t in ((419, 415, "區　分"), (444, 413, "進貨及"), (444, 420, "費　用"), (473, 413, "固　定"),
                    (473, 420, "資　產"), (419, 427, "得扣抵"), (419, 444, "不　得"), (419, 452, "扣　抵")):
        pg.text(x, y, t, 5.5, "mingliu.ttc", C, anchor="ms")
    if inv.get("note_seal"):
        pg.stamp(450, 384, name_seal(inv["note_seal"], w=40, h=14), 0, 0.8)
    pg.hand(494, 410, inv["period_short"].replace("-", " — "), 15, inv.get("period_hs", hs), color=BLUE)

    pg.text(72, 435, "買 受 人：", 10, "mingliu.ttc", C)
    mode = inv.get("buyer_mode", "hand")
    if mode == "hand":
        pg.hand(116, 435, ORG1 + ORG2, 15.5, hs, gap=-1.2)
    elif mode == "hand2":
        pg.hand(112, 427, ORG1, 11, hs, gap=-0.5)
        pg.hand(134, 440, ORG2, 11, hs, gap=-0.5)
    else:  # 橡皮章蓋印抬頭
        pg.stamp(196, 433, text_seal(ORG1 + ORG2, (40, 40, 60), 166, 12, 8, frame=False, fname="msjhbd.ttc"), 0.4, 0.95)
    pg.text(72, 450, "統一編號：", 10, "mingliu.ttc", C)
    for i, c in enumerate(BUYER_UBN):
        x = 122 + i * 16.5
        pg.rect(x, 438, x + 16.5, 455, C, 0.6)
        if mode == "stamp":
            pg.text(x + 8.25, 453, c, 13, "timesbd.ttf", (40, 40, 60), anchor="ms")
        else:
            pg.hand(x + 2.5, 453, c, 14, hs)
    pg.text(262, 449, "中 華 民 國", 10, "mingliu.ttc", C)
    pg.text(314, 449, f"{inv['roc_year']}年", 10, "msjhbd.ttc", C)
    pg.hand(345, 450, inv["month"], 14, hs)
    pg.text(362, 449, "月", 10, "mingliu.ttc", C)
    pg.hand(375, 449, inv["day"], 14, hs)
    pg.text(398, 449, "日", 10, "mingliu.ttc", C)
    pg.text(72, 468, "地　　址：", 9, "mingliu.ttc", C)
    for x, t in ((158, "縣市"), (262, "路街"), (306, "段"), (338, "巷"), (370, "弄"), (406, "號"), (440, "樓"), (474, "室")):
        pg.text(x, 468, t, 7.5, "mingliu.ttc", C)
    pg.text(210, 462, "鄉鎮", 6, "mingliu.ttc", C)
    pg.text(210, 469, "市區", 7, "mingliu.ttc", C)

    # 表格
    L, R = 72, 485
    rows = [471, 484, 501, 518, 535, 553, 571, 585, 607, 623]
    pg.rect(L, rows[0], R, rows[-1], C, 0.8)
    for y in rows[1:7]:
        pg.line(L, y, 357 if y not in (484, 571) else R, y, C, 0.6)
    pg.line(357, 501, R, 501, C, 0.6)
    pg.line(357, 520, R, 520, C, 0.6)
    for y in rows[7:-1]:
        pg.line(L, y, 357, y, C, 0.6)
    for x in (186, 229, 276, 357):
        pg.line(x, rows[0], x, rows[6] if x != 276 else rows[-1], C, 0.6)
    pg.line(357, rows[6], 357, rows[-1], C, 0.6)
    s = 9
    for x, t, a in ((80, "品", "ls"), (178, "名", "rs"), (190, "數　 量", "ls"), (233, "單　 價", "ls"),
                    (280, "金", "ls"), (350, "額", "rs"), (372, "備", "ls"), (475, "註", "rs")):
        pg.text(x, 481, t, s, "mingliu.ttc", C, anchor=a)
    pg.text(492, 482, "編號：", 9, "mingliu.ttc", C)
    pg.text(421, 534, "營業人蓋用統一發票專用章", 8.5, "mingliu.ttc", C, anchor="ms")
    pg.text(80, 582, "銷　　　售　　　額　　　合　　　計", s, "mingliu.ttc", C)
    pg.text(80, 600, "營　　 業　　 稅", s, "mingliu.ttc", C)
    pg.line(152, 585, 152, 607, C, 0.6)
    for x in (186, 229):
        pg.line(x, 585, x, 607, C, 0.6)
    pg.line(152, 593, 276, 593, C, 0.5)
    pg.text(158, 591, "應　稅", 7, "mingliu.ttc", C)
    pg.text(192, 591, "零稅率", 7, "mingliu.ttc", C)
    pg.text(238, 591, "免　稅", 7, "mingliu.ttc", C)
    pg.text(85, 617, "總", s, "mingliu.ttc", C)
    pg.text(268, 617, "計", s, "mingliu.ttc", C, anchor="rs")
    daxie_row(pg, 623, 639, C, hs, inv["total"])

    def footnote(y: float, color, label: str) -> None:
        pg.text(30, y, "※應稅、零稅率、免稅之銷售額應分別開立統一發票，並應於各該欄打「√」。", 6.5, "mingliu.ttc", color)
        pg.text(30, y + 8, "買受人註記欄之註記方法：營業人購進貨物或勞務應先按其用途區分為「進貨及費用」與「固定資產」，其進項稅額，除營業稅法第十九條第一項屬不", 5.3, "mingliu.ttc", color)
        pg.text(30, y + 15, "可扣抵外，其餘均得扣抵，並在各該欄內打「√」符號。", 5.3, "mingliu.ttc", color)
        pg.text(420, y + 2, label, 8, "mingliu.ttc", color)

    footnote(646, C, "第二聯　扣抵聯")

    # 手寫內容
    items = inv["items"]
    item_size = inv.get("item_size", 12)
    for i, (name, qty, price, amt) in enumerate(items):
        yb = rows[i + 2] - 3.5
        pg.hand(75, yb, name, item_size, hs, gap=inv.get("item_gap", -1.2))
        pg.hand(190 if len(str(qty)) > 2 else 200, yb, str(qty), 12 if len(str(qty)) <= 2 else 10, hs)
        pr = (f"{price:,}" if hs.num_comma else str(price)) if price is not None else ""
        pg.hand(232, yb, ("-" if amt < 0 and price is not None else "") + pr, 10, hs, gap=-0.6)
        a = (f"{abs(amt):,}" if hs.num_comma else str(abs(amt)))
        pg.hand(286, yb, ("-" if amt < 0 else "") + a + hs.tail, 11, hs, gap=-0.4)
    if len(items) < 5:  # 劃記空白列
        y0 = rows[len(items) + 1] + 3
        pg.line(318, y0, 316, 566, hs.color, 1.0)
    pg.hnum(285, 583, inv["net"], 13, hs)
    pg.hand(165, 605, "✓", 13, hs)
    pg.hnum(292, 604, inv["tax"], 12.5, hs)
    pg.hnum(285, 621, inv["total"], 12.5, hs)
    pg.stamp(421, 585, invoice_seal(inv["seller"]), inv.get("seal_angle", 5), 0.9)

    if inv.get("third_copy"):  # 第三聯收執聯（複寫）下緣露出
        daxie_row(pg, 668, 684, RED_FORM, hs, inv["total"], carbon=True)
        footnote(691, RED_FORM, "第三聯　收執聯")
        addr = text_seal(inv["seller"]["addr"], BLUE, 118, 10, 6.8, frame=False, fname="msjhbd.ttc")
        pg.stamp(426, 670, addr, inv.get("seal_angle", 5), 0.8)


# ───────────────────────── 掃描效果與輸出 ─────────────────────────
def scan_effect(img: Image.Image, seed: int, rot: float = -0.35, blur: float = 0.7, noise: float = 0.04,
                paper: tuple[int, int, int] = (250, 249, 245), staple: tuple[float, float, float, float] | None = (15, 40, 13, 75)) -> Image.Image:
    """模擬掃描：微傾斜、紙色、模糊、雜訊、裝訂痕。"""
    random.seed(seed)
    img = img.rotate(rot, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    d = ImageDraw.Draw(img)
    if staple:
        d.line(tuple(P(v) for v in staple), fill=(70, 70, 70), width=P(1.2))
    img = img.filter(ImageFilter.GaussianBlur(blur))
    img = Image.blend(img, Image.effect_noise(img.size, 10).convert("RGB"), noise)
    return Image.blend(img, Image.new("RGB", img.size, paper), 0.06)


def save_outputs(img: Image.Image, stem: str, truth: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    pdf_path = OUT_DIR / f"{stem}.pdf"
    try:
        img.save(pdf_path, "PDF", resolution=DPI, quality=85, title=stem)
        (OUT_DIR / f"{stem}.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"輸出失敗：{e}") from e
    return pdf_path
