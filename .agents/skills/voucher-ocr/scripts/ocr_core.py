"""OCR 核銷憑證辨識：共用元件（設定、LLM 封裝、PDF 轉圖、欄位驗證）。"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pymupdf
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

SKILL_DIR = Path(__file__).resolve().parent.parent  # .agents/skills/voucher-ocr
ROOT = Path.cwd()  # 專案根目錄（請在專案根目錄執行）
load_dotenv(find_dotenv(usecwd=True))

# 輸出欄位（CSV 與 Excel 共用順序）
FIELDS = ["會計科目", "控帳編號", "發票號碼", "發票金額", "總計金額", "發票統編", "發票抬頭", "負債科目", "計畫代號"]
META = ["待確認欄位", "備註", "來源檔案", "辨識時間", "使用模型"]
CSV_COLUMNS = FIELDS + META
MONEY_FIELDS = {"發票金額", "總計金額"}


# ───────────────────────── 設定 ─────────────────────────
@dataclass
class Stage:
    model: str
    base_url: str
    api_key_env: str
    max_tokens: int = 16000

    @property
    def enabled(self) -> bool:
        return bool(self.model)


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or SKILL_DIR / "ocr_config.toml"
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SystemExit(f"設定檔讀取失敗 {p}：{e}") from e


def stage(cfg: dict[str, Any], name: str) -> Stage:
    s = cfg.get(name, {})
    return Stage(s.get("model", ""), s.get("base_url", ""), s.get("api_key_env", "OPENAI_API_KEY"),
                 int(s.get("max_tokens", 16000)))


# ───────────────────────── LLM 封裝 ─────────────────────────
@lru_cache(maxsize=None)
def _client(base_url: str, api_key_env: str) -> OpenAI:
    key = os.getenv(api_key_env)
    if not key:
        raise SystemExit(f"環境變數 {api_key_env} 未設定（請在 .env 設定）")
    return OpenAI(base_url=base_url or os.getenv("OPENAI_BASE_URL"), api_key=key, timeout=300, max_retries=2)


def call_llm(st: Stage, prompt: str, images: list[bytes] | None = None, max_tokens: int | None = None) -> str:
    """統一呼叫入口：文字＋（可選）多張 PNG 圖片，回傳模型文字輸出。"""
    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}}
        for b in images or []
    ]
    content.append({"type": "text", "text": prompt})
    try:
        r = _client(st.base_url, st.api_key_env).chat.completions.create(
            model=st.model, messages=[{"role": "user", "content": content}], max_tokens=max_tokens or st.max_tokens, temperature=0)
        msg = r.choices[0].message
        # 部分模型（如 Muse-Glimmer）偶爾把答案放在 reasoning_content、content 為空
        return msg.content or getattr(msg, "reasoning_content", None) or ""
    except Exception as e:  # 統一轉成可讀錯誤，不洩漏金鑰
        raise RuntimeError(f"模型 {st.model} 呼叫失敗：{type(e).__name__}: {str(e)[:200]}") from e


def parse_json(text: str) -> dict[str, Any]:
    """從模型輸出取出第一個 JSON 物件（容忍 ```json 包裝與前後說明文字）。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    dec, found = json.JSONDecoder(), []
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and len(obj) >= 3:
            found.append(obj)
    if not found and "{" in text:  # 輸出被截斷：補上結尾後再試（已讀到的欄位保留，缺的欄位之後會被標為未辨識）
        body = text[text.index("{"):].rstrip().rstrip(",")
        for tail in ("}", "]}", '"]}', '"}', 'null}'):
            try:
                obj = json.loads(body + tail)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and len(obj) >= 3:
                found.append(obj)
                break
    if not found:
        raise ValueError(f"模型輸出不含 JSON：{text[:200]!r}")
    return found[-1]  # 取最後一個（模型若先複述提示範本，最後才是答案）


# ───────────────────────── PDF 與 OCR 文字 ─────────────────────────
def render_pages(pdf: Path, dpi: int) -> list[bytes]:
    try:
        with pymupdf.open(pdf) as doc:
            return [p.get_pixmap(dpi=dpi).tobytes("png") for p in doc]
    except Exception as e:
        raise RuntimeError(f"PDF 轉圖失敗 {pdf.name}：{e}") from e


def html_to_text(s: str) -> str:
    """把 chandra 的 HTML 版面輸出轉成精簡文字（保留表格的列與欄分隔）。"""
    s = re.sub(r"<br\s*/?>", " / ", s)
    s = re.sub(r"</t[dh]>", " | ", s)
    s = re.sub(r"</(tr|p|div|table)>", "\n", s)
    s = re.sub(r'<img alt="([^"]*)"\s*/?>', r"[圖：\1]", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return "\n".join(ln.strip() for ln in s.splitlines() if ln.strip())


# ───────────────────────── 驗證工具 ─────────────────────────
def valid_ubn(s: str) -> bool:
    """統一編號檢查碼（財政部新制：加權和可被 5 整除；第 7 碼為 7 時可 +1）。"""
    if not re.fullmatch(r"\d{8}", s or ""):
        return False
    w = [1, 2, 1, 2, 1, 2, 4, 1]
    t = sum(sum(divmod(int(c) * k, 10)) for c, k in zip(s, w))
    return t % 5 == 0 or (s[6] == "7" and (t + 1) % 5 == 0)


_D = {c: i for i, c in enumerate("零壹貳參肆伍陸柒捌玖")} | {"叁": 3, "叄": 3, "陆": 6, "两": 2, "〇": 0,
                                                           "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_U = {"拾": 10, "佰": 100, "仟": 1000, "十": 10, "百": 100, "千": 1000}


def parse_upper(s: str, grid: bool = False) -> int | None:
    """中文大寫金額轉整數（例：新台幣參拾壹萬伍仟肆佰貳拾元整 → 315420）。

    grid=True：發票的「億仟佰拾萬仟佰拾元」預印格，未填數字的單位視為 0。
    """
    s = re.sub(r"[新臺台幣元整圓\s/|—\-]", "", s or "")
    if not s:
        return None
    total, section = 0, 0
    num: int | None = None  # None = 單位前沒寫數字；0 = 明寫「零」
    for ch in s:
        if ch in _D:
            num = _D[ch]
        elif ch in _U:
            section += (num if num is not None else (0 if grid else 1)) * _U[ch]
            num = None
        elif ch in "萬万":
            total += (section + (num or 0)) * 10_000
            section, num = 0, None
        elif ch in "億亿":
            total = (total + section + (num or 0)) * 100_000_000
            section, num = 0, None
        else:
            return None
    return total + section + (num or 0)


def to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[^\d\-]", "", str(v))
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def norm_id(v: Any) -> str:
    """號碼類欄位：去空白、全形轉半形、英文大寫。"""
    s = str(v or "").strip()
    s = s.translate({0xFF10 + i: 0x30 + i for i in range(10)})
    return re.sub(r"\s+", "", s).upper()
