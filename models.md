# Models 可用模型清單與多模態能力實測表

> **來源端點**：`GET https://portal.genai.nchc.org.tw/api/v1/models`  
> **金鑰設定**：透過 `.env` 的 `OPENAI_API_KEY` 載入（請參考 [`.env.example`](.env.example)）  
> **最後實測時間**：2026-11-08（已透過真實圖片、OCR 圖檔與「人工智慧測試一二三」語音檔進行真實驗證）

---

## 🌟 1. Chat / 多模態模型能力矩陣（`model_mode: chat`）

> 端點：`POST https://portal.genai.nchc.org.tw/api/v1/chat/completions`

| 模型 ID | 定位與說明 | 🗣️ 文字對話 | 🖼️ 看圖 (`image_url`) | 🎧 聽聲音 (`input_audio`) | 🛠️ 工具呼叫 (`tools`) | 實測狀態與延遲 |
|---|---|:---:|:---:|:---:|:---:|---|
| **`Inkling-Small`** | 輕量全能多模態（Omni）模型 | ✅ | ✅ 真實看圖 | ✅ **真實聽音** | ✅ `tool_calls` | ✅ 可用 (~0.45s) |
| **`Muse-Spark-Open-816B-A42B`** | 大型全能多模態 MoE（總 816B / 啟用 42B） | ✅ | ✅ 真實看圖 | ✅ **真實聽音** | ✅ `tool_calls` | ✅ 可用 (~0.35s) |
| **`Muse-Glimmer-30B`** | 30B 視覺語言（VLM）模型 | ✅ | ✅ 真實看圖 | ❌ 不支援音訊 | ✅ `tool_calls` | ✅ 可用 (~0.28s) |
| **`chandra-ocr-2`** | 文件與圖片 OCR 視覺辨識模型 | ✅ | ✅ **專精 OCR 辨字** | ❌ 不支援音訊 | ✅ `tool_calls` | ✅ 可用 (~0.50s) |

### 🔍 多模態實測細節說明
- **全能多模態（可看圖 + 可聽聲音）**：
  - **`Inkling-Small`** 與 **`Muse-Spark-Open-816B-A42B`** 皆支援在 `/chat/completions` 中同時或分別傳入圖片（`image_url`）與音訊（`input_audio`），實測傳入「人工智慧測試一二三」WAV 語音檔，兩者皆能精準聽出「人工智慧測試一二三」。
- **視覺多模態（可看圖，不可聽聲音）**：
  - **`Muse-Glimmer-30B`**：可精準辨識圖片顏色與內容，但傳入音訊時會回覆無法接收音訊檔案。
  - **`chandra-ocr-2`**：針對含有文字的圖片（如 `"NIAR 2026"`）能精準輸出 OCR 文字辨識結果，不支援音訊輸入。
- **工具呼叫（Function Calling）**：4 個 `chat` 模型全數支援 OpenAI 標準 `tools` 參數並能正確回傳 `tool_calls`。

---

## 📊 統計摘要

| 分類 | 模型數量 | 可看圖 | 可聽音 | 可用數量 |
|---|:---:|:---:|:---:|:---:|
| **Omni 全能多模態 (`Inkling-Small`, `Muse-Spark-Open-816B-A42B`)** | 2 | ✅ | ✅ | **2 / 2** ✅ |
| **VLM 視覺 / OCR (`Muse-Glimmer-30B`, `chandra-ocr-2`)** | 2 | ✅ | ❌ | **2 / 2** ✅ |
| **總計** | **4** | **4** | **2** | **4 / 4 可用** |

---

## 🚀 多模態呼叫格式範例

### 1. 看圖理解（Vision：`Inkling-Small` / `Muse-Glimmer-30B` / `Muse-Spark-Open-816B-A42B` / `chandra-ocr-2`）
```json
{
  "model": "Inkling-Small",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "請描述這張圖片或辨識其中的文字"},
        {
          "type": "image_url",
          "image_url": {"url": "data:image/png;base64,<BASE64_ENCODED_PNG>"}
        }
      ]
    }
  ]
}
```
