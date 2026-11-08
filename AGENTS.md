# Agent Rules

## Env & Tools

- Python 3.11+，一律使用 `uv` 管理專案與虛擬環境（路徑為 `.venv`）。
- 安裝套件一律使用 `uv add`，執行腳本一律使用 `uv run`（禁止直接使用 `pip` 或 `python`）。

## Security

- 禁止 hardcode API Key；程式碼一律透過 `dotenv` 搭配 `os.getenv()` 讀取（變數名稱請參考 `.env.example`），範例統一使用 `"your-api-key"` 佔位。
- 禁止 Agent 讀取或檢視 `.env`、`*.key` 等機密檔案內容；禁止在 log / print / 報錯中印出金鑰。

## Code & Behavior

- 需加上 Type Hints 與 `try...except` 錯誤處理；LLM 呼叫一律抽離為專用封裝函式（統一管理 client、model 與例外處理）。
- 僅修改指定功能，直接給出最小可執行代碼；註解與說明一律使用繁體中文。

## API & Models

- `.env` 變數：`OPENAI_BASE_URL`（預設 `https://portal.genai.nchc.org.tw/api/v1`）、`OPENAI_API_KEY`、`DEFAULT_MODEL`（詳見 `.env.example`）。
- 可用 Chat 模型（皆支援 `tools`）：
  - 全模態（文＋`image_url` 看圖＋`input_audio` 聽音）：`Inkling-Small`、`Muse-Spark-Open-816B-A42B`
  - 視覺／OCR（文＋`image_url` 看圖，不支援音訊）：`Muse-Glimmer-30B`、`chandra-ocr-2`（專精 OCR）
