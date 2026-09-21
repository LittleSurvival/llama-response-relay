# Llama.cpp Launcher

Windows 用的 llama.cpp 圖形化啟動器。可保存多個模型 Profile、隱藏執行 `llama-server.exe`，並透過內建 LRR interceptor 對 OpenAI 相容回應套用術語表。關閉 Launcher 時會停止由它啟動的 LRR 與 llama.cpp。

桌面介面使用 PyQt6。本專案目前以符合 PyQt6 GPL 授權的方式開發與散布；若未來需要閉源或其他不相容的散布方式，必須先取得適用的商業授權或改用相容的 Qt binding。

## 環境與啟動

需求：

- Windows 11
- Python 3.11 以上（直接使用原始碼時）
- 已下載的 llama.cpp Windows 版本
- 一個或多個 `.gguf` 模型

開發模式：

```powershell
python -m pip install -e ".[dev]"
python launcher.py
```

程式不會下載 llama.cpp 或模型。第一次啟動後：

1. 在 `llama.cpp` 選擇直接包含 `llama-server.exe` 的資料夾。
2. 在 `Models` 選擇直接包含 `.gguf` 的資料夾。
3. 按左下角 `New profile`，先命名 Profile，再選擇模型並填寫參數。
4. 視需要到 `LRR` 啟用 interceptor、設定 host／port，並建立術語表。
5. 在 `LRR` 的 `Glossaries` 選擇要套用的術語表，再回到 Settings 選擇 Profile 並按 `Start`。

資料夾只讀取第一層，不會遞迴掃描子資料夾或整個磁碟。

左側 Profile 清單提供 `Rename`、`Copy`、`Delete`。右上角以 `Settings`、`LRR`、`Runtime` 分開顯示 Profile 設定、response relay／術語表和程序資訊；模型載入期間會顯示動態進度，`Stop` 仍可立即使用。

## 設定與 Profile

設定保存在：

```text
%LOCALAPPDATA%\LlamaCppLauncher\settings.json
```

寫入前會驗證並以暫存檔原子替換。若設定檔損毀，程式會顯示錯誤且不覆寫原檔。

每個 Profile 包含：

- Profile 名稱
- 模型路徑
- `--host`
- `--port`
- `-ngl`
- `-c`
- `-np`
- `-fa`：`auto`、`on` 或 `off`
- `--no-mmap`
- GPU mode：`auto`、`single` 或 `multi`
- Custom arguments

`auto` 不加入 GPU topology 參數。`single` 與 `multi` 會先讀取所選 `llama-server.exe --help`，確認支援 `--split-mode` 後才啟動。

Custom arguments 使用 Windows 命令列引號規則解析，但不能重複 Profile 已管理的參數，例如 `--port`、`-ngl` 或 `--no-mmap`。

## LRR 與術語表

LRR 預設啟用並監聽 `127.0.0.1:8081`，llama.cpp 預設仍由 Profile 的 `127.0.0.1:8080` 提供上游服務。啟用時，用戶端應改連線到 LRR：

```text
http://127.0.0.1:8081
```

目前支援：

- `POST /v1/chat/completions`
- `POST /v1/completions`
- `GET /v1/models`（原樣轉送，不套用術語表）
- 一般 JSON 與 `text/event-stream` 串流回應

只會更換 assistant completion 的文字欄位，不修改 reasoning、tool calls、usage、錯誤內容或其他 metadata。串流文字跨 chunk 時也能正確匹配。

LRR 會處理瀏覽器的 CORS preflight，並在一般、串流及錯誤回應加入非 credential 模式的跨來源 header，因此 Web UI 應把 API base URL 設為 Client endpoint。由於任何網頁都能呼叫可連線的 LRR，請保留 loopback host；若改成非 loopback，務必自行限制防火牆與網路存取。

術語表與 Profile 是兩套獨立資料：可在 `LRR` 頁新增、命名、儲存與刪除多個術語表；LRR 直接使用 `Glossaries` 目前選取的術語表，不會把術語表設定寫入 Profile。Settings 頁不包含術語表設定。每筆規則包含來源文字、替換文字、啟用狀態與大小寫敏感設定；新規則預設啟用大小寫敏感。規則只接受純文字，不使用正規表示式，來源互相重疊時優先採用最長匹配，替換結果不會再次遞迴替換。

每次啟動會取得當前所選術語表的快照。執行中禁止修改 Profile 與術語表；要套用後續變更請先停止再啟動。若把 LRR host 設為非 loopback 位址，服務可能暴露在區域網路，請自行確認防火牆與存取風險。

若關閉 `Enable LRR interceptor`，Launcher 只啟動 llama.cpp，不監聽 LRR port，也不套用術語表。此時用戶端直接連線到 Runtime 顯示的 upstream llama.cpp endpoint；已儲存的 LRR endpoint 與目前選取的術語表不會被刪除。

## 程序與狀態

- 同一時間只啟動一個 Profile。
- llama.cpp Console 不會顯示，stdout／stderr 會出現在 `Process output`。
- `Starting` 表示 llama.cpp 或 LRR 尚在啟動。
- `Ready` 表示 llama.cpp health check 成功；若 LRR 已啟用，也代表 LRR 已完成監聽。
- `Failed` 會顯示程序提前退出、健康檢查逾時、LRR port 被占用或其他啟動錯誤。
- `Stop`、`Restart` 與關閉視窗會先停止 LRR，再操作 Launcher 自己持有的 llama.cpp 程序 handle，不會依程序名稱關閉其他 llama.cpp。

Runtime 頁上方是固定高度的狀態 dashboard，下方仍保留程序輸出。Launcher 會在該版本支援時自動啟用 llama.cpp 的 `/metrics` 與 `/slots`，每秒於背景擷取一次，UI 執行緒不會直接進行網路請求。圖表只保留目前程序最近五分鐘、最多 300 筆取樣；Stop 後保留最後快照，Restart 則從全新的 session 重新計算。

Dashboard 顯示：

- Profile、生命週期狀態、運行時間、upstream 與 Client endpoint。
- 目前／平均 prompt 與 generation token/s、session 輸入／輸出 token。
- active／total slots、slot 覆蓋率與 deferred request 數量。
- 最近一筆經由 LRR Client endpoint 的 completion：輸入、輸出、cache token 比例、llama.cpp prompt＋generation 計算時間、首個可見 byte（TTFT）與完整請求時間。
- Prompt／generation throughput，以及 slot occupancy／deferred request 的五分鐘走勢。

Runtime 頁另有可收合的 Hardware dashboard。頁面可見時每秒於獨立背景執行緒更新，切換到其他頁面會暫停，返回時立即重新取樣；即使 llama.cpp 尚未啟動，整機資料仍會顯示。內容包括：

- 全系統 CPU usage 圓環、透過 Windows performance counter 每秒追蹤的動態平均 CPU frequency，以及 Launcher 持有的 llama-server process CPU 使用率。
- 每張 NVIDIA、AMD、Intel GPU 各自的 usage／VRAM 圓環，以及 clock、VRAM used/total、temperature 文字。
- 多張 GPU 超出可用寬度時使用橫向捲動，不會壓縮或覆蓋卡片。

NVIDIA 優先透過 NVML 讀取；AMD、Intel 與 NVIDIA fallback 使用 LibreHardwareMonitor。顯卡驅動、裝置世代、權限或個別 sensor 不支援時，對應欄位會顯示 `Unavailable`，不會阻止 Launcher 啟動。這一版不監控 CPU temperature，也不安裝或修改硬體驅動。

LRR 只保留最近任務的數值摘要，不保存 prompt、response 文字或串流內容。直接呼叫 upstream llama.cpp endpoint 的任務不會出現在「Latest client task」，但若 `/metrics` 可用，仍會反映在 server-wide token 與 throughput 數字中。

`Unsupported` 表示目前 llama.cpp build 沒有對應 flag／endpoint；`Unavailable` 表示尚未取得資料或本次輪詢失敗；連續三個輪詢週期失敗後顯示 `Stale`，同時保留最後已知值。各 telemetry 來源獨立判定，因此其中一個來源失敗時其他資料仍可正常更新。

第一版沒有系統匣、Windows 自動啟動、最小化啟動、多個同時執行的 Profile 或模型下載功能。

## 測試

```powershell
python -m pytest
```

PyQt6 UI 手動狀態預覽：

```powershell
$env:UI_PREVIEW_STATE = "Ready"
$env:QT_SCALE_FACTOR = "1.5"
python tests\manual_ui_preview.py
```

## 建置 Windows EXE

`build.bat` 是本專案唯一正式建置入口。直接雙擊即可一鍵建置；腳本會建立獨立的 `.build-venv`、安裝所需套件、執行完整測試、正常關閉正在使用舊版輸出的 Launcher、移除舊 onedir，並在完成後開啟輸出位置。這能避免全域 Python 的過時套件或缺少 PyQt6 造成損壞的 bundle。

打包階段會隔離 `PATH`，避免其他工具附帶的 Qt／Windows runtime DLL 被誤收進 EXE。完成前會使用隔離的資料目錄實際啟動 onefile EXE，驗證 Qt 頁面、設定儲存與硬體 provider 載入；若啟動失敗或逾時，建置會判定失敗。診斷結果保留在 `.tmp/packaged-smoke-*`，不會覆寫使用者的 profile 或術語表。

輸出位於：

```text
dist\LlamaCppLauncher.exe
```

採用 `onefile` 且不顯示額外 Console，因此發布與移動時只需要 `LlamaCppLauncher.exe`。程式啟動時會把內含的 Python、PyQt6、aiohttp 與硬體監控 runtime 暫時解壓到系統 `%TEMP%`；`llama-server.exe`、顯卡驅動與模型仍由使用者從 UI 選擇或自行安裝，不會包含在 EXE 內。
