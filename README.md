# AI Workshop：核銷憑證辨識（voucher-ocr）

把掃描的核銷憑證 PDF 交給 AI 助理（Claude Code 或 Antigravity），用平常說話的方式，就能整理出「自動立帳」需要的欄位，不需要寫程式。

## 可以做什麼

- 🧾 讀取核銷憑證掃描檔：上半部黏存單＋下半部統一發票、電子發票或免用發票收據，印刷字與手寫字都能讀
- 📋 擷取自動立帳欄位：會計科目、控帳編號、發票號碼、發票金額、總計金額、發票統編、發票抬頭、負債科目、計畫代號
- 📂 一個 PDF 產生一個 CSV，再彙整成一份 Excel；新一批資料只處理新的 PDF，舊資料不會被覆蓋
- 🟨 有疑問的格子自動塗**螢光黃**並附原因；找不到的欄位留空，不會亂填
- ✍️ 延伸練習：不用技能，只用一段自然語言辨識[手寫直式作文](#延伸練習手寫直式作文辨識不用技能只用自然語言)

> 第一次使用前，請先完成文件後半段的〈[第一次使用前的設定](#第一次使用前的設定可請講師協助)〉，或請講師協助。

## 範例：先用去識別化樣本試一次

[example_deid/](example_deid/) 有 5 份去識別化的憑證（單位、廠商、金額、統編全是虛構的），適合第一次練習。在 AI 助理的對話框輸入：

> 幫我把 example_deid/ 裡的核銷憑證轉成 CSV，並彙整成 Excel

AI 助理會跳出選單問你 3 個問題。**不確定怎麼選時，每題都選標有 (Recommended) 的選項就好。**

| 問題 | 白話說明 |
| --- | --- |
| 1. 辨識模式 | 選建議的「Muse-Spark 看圖＋Glimmer 複核」：兩個 AI 各讀一次，讀到不一樣的地方就標黃 |
| 2. 已經辨識過的檔案 | 選建議的「只處理新的 PDF」：做過的不會重做，也不會被覆蓋 |
| 3. 完成後 | 選建議的「產生 CSV 並彙整成 Excel」 |

5 份大約 1 分鐘。完成後打開 `output/excel/核銷彙整.xlsx`，會看到類似這樣的結果（節錄）：

| 項次 | 會計科目 | 控帳編號 | 發票號碼 | 發票金額 | 總計金額 | 發票統編 | 計畫代號 |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | 03-1111-03114Z1500-0000-51330612-00-00 | 203114009187 | KX52816403 | 315,420 | 315,420 | 23831903 | 03114Z1500 |
| 2 | 03-1111-03114Z1600-0000-51331205-00-00 | 203114006142 | QA48017256 | 184,275 | 184,275 | 16480894 | 03114Z1600 |
| 3 | 03-1111-03114Z1500-0000-51330688-00-00 | 203114007326 | 收據 | 3,250 | 3,250 | 17784483 | 03114Z1500 |

- 發票抬頭都是「財團法人未來科技研究院智慧雲端運算中心」；負債科目是固定值，計畫代號取會計科目第 9 碼起 10 碼。
- 每份樣本旁邊有同名的 `.json` 標準答案，可以對照 AI 讀得對不對。
- 免用發票收據沒有發票號碼，會填「收據」。

## 看到黃色格子怎麼辦

滑鼠移到黃色格子上，會顯示原因。例如某張發票的買受人名稱手寫成兩行，AI 只讀到第一行：

> 發票抬頭：與本單位名稱不同，可能只讀到一部分

對照原始 PDF 後：

1. 打開 `output/csv/` 裡同名的 CSV，把該欄改成正確內容，並把「待確認欄位」裡已確認的欄位名稱刪掉。
2. 回到對話框輸入：
   > 重新彙整核銷憑證的 Excel

**請改 CSV，不要直接改 Excel**：Excel 每次都會從 CSV 重新產生，舊版會自動備份到 `output/excel/backup/`。

## 處理自己的資料

1. 把新一批 PDF 放進一個資料夾，例如 `test/`（可以有子資料夾）。
2. 在對話框輸入：
   > 幫我把 test/ 裡的核銷憑證轉成 CSV，並彙整成 Excel
3. 之後有新的 PDF，放進同一個資料夾、再說一次同一句話即可：**只會處理新的 PDF**，彙整的 Excel 會包含全部資料。

## 兩種用法：AI 助理直接看 vs 使用技能

同一件事可以用兩種方式完成，建議兩種都試一次，比較差別。

### 用法一：AI 助理直接看（不用技能）

AI 助理本身就看得懂圖片，可以直接請它讀 PDF。因為技能會依你說的話自動啟用，**請在句子裡註明不要使用技能**：

> 不要使用任何技能。請直接看 example_deid/SKM_650i25101515340_deid.pdf 這份核銷憑證，幫我找出會計科目、控帳編號、發票號碼、發票金額、總計金額、發票統編（賣方的統編）、發票抬頭，整理成表格。找不到的欄位留空，不確定的請標註。

接著可以追問：

- 「發票上的統編，檢查碼算起來正確嗎？」
- 「黏存單的核銷金額和發票總計一致嗎？中文大寫換算後也對嗎？」
- 「把剛剛的結果存成 output/native/SKM_650i25101515340_deid.csv」

### 用法二：使用核銷憑證辨識技能

> 幫我把 example_deid/ 裡的核銷憑證轉成 CSV，並彙整成 Excel

其他常用說法：

| 想做的事 | 可以這樣說 |
| --- | --- |
| 只處理新加入的檔案 | test/ 有新的 PDF，幫我只處理新的並更新 Excel |
| 重做某一份 | SKM_650i25101515340_deid.pdf 重新辨識一次 |
| 保留整頁辨識原文（稽核用） | 用 chandra 模式處理 example_deid/，要保留整頁辨識原文 |
| 速度優先 | 不要複核，快速處理 test/ 的核銷憑證 |
| 檢查待確認項目 | 列出 Excel 裡所有黃色的格子和原因 |
| 對照原件 | 打開黃色格子那份的原始 PDF，幫我對照那一格 |
| 改完 CSV 後更新 | 重新彙整核銷憑證的 Excel |
| 比較模型 | 用 example_deid 比較各模型的辨識準確率 |

### 兩種用法比較

| | 用法一：AI 助理直接看 | 用法二：使用技能 |
| --- | --- | --- |
| 準備工作 | 不用，馬上可以試 | 需完成第一次使用前的設定 |
| 誰讀圖片 | AI 助理本身（Claude、Gemini 等） | 國網中心 GenAI Portal 的模型（`Muse-Spark-Open-816B-A42B` 擷取＋`Muse-Glimmer-30B` 複核） |
| 資料送到哪裡 | 掃描圖片送到 AI 助理的服務商 | 掃描圖片送到國網中心；AI 助理只讀辨識後的文字結果 |
| 檢查規則 | 要自己記得逐項追問 | 自動檢查統編檢查碼、金額勾稽、中文大寫、兩個模型比對、重複請款 |
| 輸出格式 | 每次可能略有不同 | 固定欄位的 CSV 與 Excel，有疑問的格子塗黃 |
| 大量檔案 | 一份一份處理，容易漏 | 整個資料夾批次處理，可中斷續跑 |
| 重複執行 | 每次重新看圖 | 已處理的檔案自動略過，舊資料自動備份 |
| 適合 | 臨時看一兩份、探索新格式的單據 | 例行、大量、要留紀錄的作業 |

> 用法一很適合用來「理解問題」：先請 AI 助理直接看幾份新格式的單據，確認要抓哪些欄位、會遇到哪些狀況，再把這些規則整理成技能，交給用法二例行處理。這個技能就是這樣做出來的。

## 使用小提醒

- **黃格一定要人工確認，沒標黃的也建議抽查。** 系統會自動比對：統編檢查碼、銷售額＋營業稅＝總計、中文大寫與數字、黏存單與發票金額、兩個 AI 的讀數、跨檔重複的控帳編號或發票號碼（可能重複請款）。
- **「發票統編」是賣方（廠商）的統編**，本單位（買方）的統編不會填進這一欄。
- **換單位使用**：修改 [ocr_config.toml](.agents/skills/voucher-ocr/ocr_config.toml) 的本單位統編與全名（`buyer_ubns`、`buyer_names`）。正式使用時，可刪掉裡面標示「測試用」的虛構單位。
- **注意機密性。** PDF 會送到國網中心 GenAI Portal 辨識，結果含真實財務資料，請依單位規定處理。
- 詳細說明見 [SKILL.md](.agents/skills/voucher-ocr/SKILL.md)。

## 延伸練習：手寫直式作文辨識（不用技能，只用自然語言）

[example_essay/](example_essay/) 放了 3 份大考中心公開的 115 學年學測國語文寫作答題卷原卷：手寫、直式、由右至左書寫在稿紙上。不是每種文件都要做成技能，一次性的任務，用一段話交代清楚就能完成。在對話框輸入：

> 請透過國網中心 GenAI Portal API（設定在 .env），用模型 Muse-Spark-Open-816B-A42B 辨識 example_essay/ 裡的手寫作文。這是直式中文作文，閱讀順序由上到下、由右到左。請逐字照原文轉成文字，不要改錯字、不要潤飾，保留標點與分段，小題標號寫成（一）（二）。沒把握的字用【辨識的字?→可能的字】標註，例如【末?→未】來。考生本身寫錯的字照抄，不要標註。每份存成 output/essay/檔名.txt。

完成後可以接著說：

> 列出所有【】標註的地方，並打開原卷讓我對照

**實測結果**（原卷 1-1，共 468 字）：

- Muse-Spark-Open-816B-A42B 直接看圖，正確率約 98%。直式的閱讀順序完全正確，考生自己的筆誤（把「展示」寫成「展式」）也照原文保留。
- 讀錯的 6 處中，有 5 處被標上【】；但建議的修正只有約一半正確，例如把「抵擋」建議成「逃避」。**【】是告訴你要看哪裡，不要直接採用建議的字。**
- 同一張圖每次辨識的結果略有不同，重要的作文可以跑兩次比對。
- 提示中的範例請用和文件無關的字（例如【末?→未】來）。若拿文件裡真的讀錯的字當範例，等於把答案寫進題目，結果會比實際好看。
- 另外比較過：chandra-ocr-2 會把稿紙的格子位置對錯，導致段落順序混亂；Muse-Glimmer-30B 無法完成轉寫。所以這裡只用 Muse-Spark。

---

## 第一次使用前的設定（可請講師協助）

以下步驟每台電腦只需要做一次，請開啟 PowerShell 依序執行。

0. **下載專案**，並進入專案資料夾（之後的指令都在這個資料夾執行）：

   ```powershell
   git clone https://github.com/gemini960114/ai-workshop-voucher-ocr.git
   cd ai-workshop-voucher-ocr
   ```

1. **安裝 [uv](https://docs.astral.sh/uv/)**（已安裝可跳過；裝完要重新開啟 PowerShell），再安裝專案需要的套件：

   ```powershell
   winget install astral-sh.uv
   uv sync
   ```

2. **設定 API 金鑰**：複製 `.env.example` 成 `.env`，把 `OPENAI_API_KEY` 改成自己的金鑰。`.env` 不會被上傳到 GitHub，請勿分享給他人。

   ```powershell
   Copy-Item .env.example .env
   ```

3. **（只有 Claude Code 需要）讓 Claude Code 找到技能**：Antigravity 會從 `.agents/skills/` 載入技能，Claude Code 則是從 `.claude/skills/`。執行下列指令建立連結，讓兩邊共用同一份（不需要系統管理員權限）：

   ```powershell
   # 建立 .claude 資料夾，並把 .claude\skills 連到 .agents\skills
   New-Item -ItemType Directory -Force .claude
   New-Item -ItemType Junction -Path .claude\skills -Target (Resolve-Path .agents\skills)

   # 確認：有指向 .agents\skills，而且看得到 SKILL.md
   Get-Item .claude\skills | Select-Object LinkType, Target
   Get-ChildItem .claude\skills\voucher-ocr
   ```

   完成後重新開啟 Claude Code（或在 VS Code 按 `Ctrl+Shift+P`，選 `Developer: Reload Window`）。在對話框輸入 `/`，看得到 `voucher-ocr` 就代表設定成功，也可以直接輸入 `/voucher-ocr` 叫用。專案規則 `AGENTS.md` 會自動載入，不用另外設定。

   - `.claude/skills` 不會被上傳到 GitHub；技能只要在 `.agents/skills/` 維護即可。
   - 要移除連結（只刪連結，不會刪到技能內容）：

     ```powershell
     (Get-Item .claude\skills).Delete()
     ```

## 專案內容

| 路徑 | 說明 |
| --- | --- |
| [example_deid/](example_deid/) | 去識別化的核銷憑證樣本（虛構資料，附標準答案 JSON） |
| [example_essay/](example_essay/) | 大考中心公開的 115 學年學測國語文寫作答題卷原卷（手寫直式作文，延伸練習用） |
| `output/` | 辨識結果：CSV、Excel 與備份（不會上傳到 GitHub） |
| [.agents/skills/voucher-ocr/](.agents/skills/voucher-ocr/) | 核銷憑證辨識技能本體（`SKILL.md` ＋ 處理程式 ＋ 設定檔） |
| [scripts/](scripts/) | 去識別化樣本產生程式（`uv run scripts/deid_docs.py`） |
| [AGENTS.md](AGENTS.md) | AI 助理在這個專案中要遵守的規則 |
| [models.md](models.md) | 國網中心 GenAI Portal 可用的 AI 模型與能力實測 |
| `.env.example` | 金鑰設定範本 |

<details>
<summary>進階：不透過 AI 助理，直接執行處理程式</summary>

```powershell
$env:PYTHONIOENCODING="utf-8"
# 1. PDF → CSV（一個 PDF 一個 CSV，已有 CSV 的會略過）
uv run .agents/skills/voucher-ocr/scripts/ocr_to_csv.py example_deid
# 2. 所有 CSV → Excel（舊 Excel 先自動備份）
uv run .agents/skills/voucher-ocr/scripts/build_excel.py
```

| 參數（ocr_to_csv.py） | 說明 |
| --- | --- |
| `--force` | 已有 CSV 的也重新辨識，舊 CSV 備份到 `output/csv/_backup/` |
| `--ocr-model chandra-ocr-2` | 先整頁 OCR 再擷取，保留整頁辨識原文（較慢，適合需要稽核紀錄時） |
| `--verify-model none` | 不做 Glimmer 複核（較快，少一道比對） |
| `--extract-model <模型>` | 改用其他擷取模型（例如地端模型，端點在 `ocr_config.toml` 設定） |
| `--out <資料夾>` | 輸出資料夾，預設 `output/` |

模型、端點、輸出上限（`max_tokens`）、本單位統編與全名都在 [ocr_config.toml](.agents/skills/voucher-ocr/ocr_config.toml) 設定。

比較不同模型的準確率：`uv run .agents/skills/voucher-ocr/scripts/bench_models.py --pdf example_deid --truth example_deid`

完整說明見 [SKILL.md](.agents/skills/voucher-ocr/SKILL.md)，或執行時加 `--help`。

</details>
