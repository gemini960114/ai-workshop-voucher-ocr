---
name: voucher-ocr
description: >-
  核銷憑證（核銷憑證黏存單＋統一發票／電子發票／收據）掃描 PDF 辨識與自動立帳資料整理。當使用者要把核銷憑證、
  發票、收據的 PDF 轉成 CSV 或 Excel，擷取會計科目、控帳編號、發票號碼、金額、統編、發票抬頭等欄位，
  批次處理新一批 PDF、彙整成 Excel，或比較不同模型的辨識準確率時，必須啟動此 Skill。
---

# 核銷憑證辨識 Skill (`voucher-ocr`)

把掃描的核銷憑證 PDF 轉成「自動立帳」欄位：**一個 PDF 一個 CSV**，再彙整成一份 Excel。有疑問的儲存格塗**螢光黃**並附原因，找不到的欄位留空、不硬填。

```
PDF ──(AI 模型讀圖＋複核)──▶ output/csv/<檔名>.csv ──(程式彙整，不用模型)──▶ output/excel/核銷彙整.xlsx
```

| 輸出欄位 | 來源 |
|---|---|
| 會計科目、控帳編號、發票號碼、發票金額、總計金額、發票統編（賣方）、發票抬頭（買方名稱） | AI 辨識 |
| 計畫代號 | 會計科目第 9 碼起取 10 碼（程式計算） |
| 負債科目 | 設定檔固定值 |
| 待確認欄位、備註、來源檔案、辨識時間、使用模型 | 程式產生 |

本 Skill 的程式與設定都在本資料夾：`scripts/`（處理程式）、[ocr_config.toml](./ocr_config.toml)（模型、本單位統編與全名、負債科目）。以下指令一律在**專案根目錄**執行。

---

## 步驟零：前置環境檢查

1. 確認專案根目錄有 `.env`（**只檢查是否存在，禁止讀取內容**）：
   ```powershell
   Test-Path .env
   ```
   不存在時請使用者依 `.env.example` 建立並填入 `OPENAI_API_KEY`。
2. 確認使用者提供的 PDF 路徑（檔案或資料夾）存在；資料夾會連子資料夾一起處理。

---

## 步驟一：互動式需求引導

使用者**尚未說明**的項目，用互動提問工具（`AskUserQuestion` 或 `ask_question`）一次問完；已說明的不要重問。使用者說「用預設」時全部採 (Recommended) 選項、不提問。

1. **辨識模式**（單選）：
   - `Muse-Spark 直接看圖 ＋ Glimmer 複核：準確度最高，每份約 25 秒 (Recommended)`
   - `chandra-ocr-2 先整頁 OCR → Muse-Spark ＋ Glimmer 複核：保留整頁辨識原文供稽核，每份約 50 秒`
   - `Muse-Spark 直接看圖、不複核：最快，每份約 15 秒，少一層數字比對`
2. **已經辨識過的檔案**（單選）：
   - `只處理新的 PDF，已有 CSV 的略過 (Recommended)`
   - `全部重新辨識（舊 CSV 自動備份到 output/csv/_backup/）`
3. **完成後**（單選）：
   - `產生 CSV 並彙整成 Excel (Recommended)`
   - `只產生 CSV`

---

## 步驟二：PDF → CSV

依第 1、2 題組合參數：

```powershell
$env:PYTHONIOENCODING="utf-8"
uv run .agents/skills/voucher-ocr/scripts/ocr_to_csv.py "<PDF 檔或資料夾>" [參數]
```

| 選擇 | 參數 |
|---|---|
| Muse-Spark 直接看圖 ＋ Glimmer 複核 | （不加，設定檔預設） |
| chandra-ocr-2 先 OCR | `--ocr-model chandra-ocr-2` |
| 不複核 | `--verify-model none` |
| 全部重新辨識 | `--force` |

- 處理時間約為「每份秒數 × 份數 ÷ 2」（預設同時處理 2 份）。份數多時請用背景執行，完成後再繼續。
- 單一檔案失敗不影響其他檔案；失敗的檔案沒有 CSV，再執行一次同樣指令就只會補做失敗的檔案。
- 使用者若指定其他模型（例如地端模型），用 `--extract-model`、`--verify-model` 覆寫；端點不同時請使用者修改 [ocr_config.toml](./ocr_config.toml) 的 `base_url` 與 `api_key_env`。

## 步驟三：CSV → Excel（第 3 題選彙整時）

```powershell
uv run .agents/skills/voucher-ocr/scripts/build_excel.py
```

- 彙整 `output/csv/` 下**所有** CSV（含先前批次），項次依來源檔名排序。
- 既有 Excel 先備份到 `output/excel/backup/核銷彙整_<日期時間>.xlsx` 再重新產生。
- 若出現「無法寫入」：請使用者先關閉 Excel 中開啟的檔案再執行。

---

## 步驟四：交付結果

1. 讀取本次產生的 CSV（`output/csv/`），用表格向使用者報告：處理份數、失敗份數、每份的待確認欄位與原因（取自「備註」欄）。
2. 附上 Excel 連結（路徑以專案根目錄為準）：`[核銷彙整.xlsx](output/excel/核銷彙整.xlsx)`，並說明：
   - **螢光黃**＝需人工確認，滑鼠移到儲存格上可看原因；空白＝文件上找不到，未硬填。
   - **修正方式**：改 `output/csv/` 中對應的 CSV（並清空該列「待確認欄位」中已確認的欄位名稱），再執行步驟三。**不要直接改 Excel**，下次彙整會被重新產生。
3. 若有待確認項目，可主動提議：「要我開啟原始 PDF 對照那幾格嗎？」

---

## 檢查規則（標黃的原因）

| 檢查 | 標黃欄位 |
|---|---|
| 欄位找不到 | 該欄 |
| 會計科目、控帳編號（12 碼）、發票號碼（2 英文＋8 數字）格式不符 | 該欄 |
| 賣方統編檢查碼不符，或誤填成本單位（買方）統編 | 發票統編 |
| 發票抬頭與設定的本單位全名不同（常見：手寫兩行只讀到一行） | 發票抬頭 |
| 銷售額＋營業稅≠總計；發票中文大寫與數字不符 | 發票金額 |
| 黏存單核銷金額、中文大寫、總計三者不一致 | 總計金額 |
| 發票金額≠黏存單總計 | 兩欄都標 |
| 複核模型讀到的號碼或金額不同 | 該欄 |
| 擷取模型自評不確定（金額已被勾稽證實時不採計） | 該欄 |
| 跨檔重複的控帳編號或發票號碼（可能重複請款） | 該欄（彙整 Excel 時檢查） |

---

## 進階用法

- **換單位使用**：修改 [ocr_config.toml](./ocr_config.toml) 的 `buyer_ubns`（本單位統編）與 `buyer_names`（本單位全名）。目前另列了 `example_deid/` 樣本的虛構單位，正式使用時可移除。
- **比較模型準確率**：準備標準答案 JSON（欄位同輸出欄位，檔名與 PDF 相同）後執行，結果寫在 `<out>/report.md`：
  ```powershell
  uv run .agents/skills/voucher-ocr/scripts/bench_models.py --pdf "<PDF 資料夾>" --truth "<答案資料夾>" --out output_bench
  ```
  比較的模型組合在 `bench_models.py` 的 `COMBOS` 中調整。
- **模型實測紀錄（2026-11，10 份樣本）**：Muse-Spark 直接看圖 69/70、chandra-ocr-2→Muse-Spark 68/70（錯誤皆已標黃）；Muse-Glimmer-30B 最快但曾讀錯號碼未自覺，只適合當複核；Inkling-Small 常漏讀統編；chandra-ocr-2 不依指示輸出欄位，只能當 OCR 第一步。

全程遵守專案根目錄 [AGENTS.md](../../../AGENTS.md)：嚴禁讀取 `.env` 或印出 API Key；辨識結果含真實財務資料，不要上傳到專案以外的地方。
