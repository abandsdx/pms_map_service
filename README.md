# Nuwa 地圖與日誌服務

## 總覽

本應用程式作為一個橋樑與工具，用於和女媧機器人 (Nuwa Robotics) 的服務進行互動。它主要有兩個功能：

1.  **地圖資料下載器**：從女媧機器人任務系統 (RMS) API 獲取地圖資料與圖片，進行處理後，透過本地 API 提供服務。
2.  **即時日誌檢視器**：連接到一個 MQTT 代理 (broker)，以接收和發送與機器人相關的事件，並在網頁介面上即時顯示。

本應用程式使用 FastAPI 框架開發，具備動態金鑰管理系統，並設計為在 Docker 環境中運行。

## 功能特性

-   **動態金鑰管理**：透過一個由主金鑰保護的管理介面，安全地管理使用者存取權。無需重啟服務即可產生、列出和撤銷使用者金鑰。
-   **主金鑰自動產生**：首次啟動時，若未提供主金鑰，系統會自動產生一個安全的金鑰，簡化了初始設定流程。
-   **動態地圖獲取**：觸發背景任務，從 Nuwa RMS API 下載並解析最新的地圖資料。
-   **資料持久化**：地圖圖片、處理後的 JSON 資料以及使用者 API 金鑰都會儲存在本地 volume 中，以防止資料遺失。
-   **獨立輸出目錄**：根據 Nuwa RMS token 的雜湊值，將不同 token 的地圖資料儲存在各自獨立的目錄中。
-   **即時事件/日誌監控**：基於 WebSocket 的網頁介面，用於檢視來自 MQTT 代理的即時日誌，此功能由使用者金鑰保護。
-   **容器化**：使用 Docker 和 Docker Compose，易於部署和運行。

## 金鑰管理

本服務採用雙層金鑰系統：
-   **主金鑰 (Master Key)**：一個高權限金鑰，專門用於存取 `/admin` 管理介面以管理使用者金鑰。此金鑰透過 `MASTER_KEY` 環境變數進行設定。
-   **使用者 API 金鑰 (User API Keys)**：標準金鑰，用於存取服務的一般功能，例如日誌檢視器 WebSocket 和 MQTT 設定 API。這些金鑰由管理員透過 `/admin` 頁面進行管理。

## 開始使用

### 1. 設定主金鑰 (建議作法)

設定此服務最簡單且安全的方式是建立一個 `.env` 檔案。`docker-compose` 會自動讀取此檔案中的環境變數。

-   **建立 `.env` 檔案**：在專案的根目錄下（與 `docker-compose.yml` 同層級）建立一個名為 `.env` 的檔案。
-   **產生並加入您的主金鑰**：在 `.env` 檔案中加入您的主金鑰。您可以使用 `openssl rand -hex 16` 來產生一個安全的金鑰。檔案內容應如下：
    ```
    MASTER_KEY=your_super_secret_master_key_here
    ```

### 2. 建置並運行服務

當 `.env` 檔案設定好後，您就可以在背景建置並運行容器：
```bash
docker-compose up -d --build
```
服務將會啟動於 `http://localhost:8000`。因為您已經提供了 `MASTER_KEY`，系統將會直接使用它。

### 備用方案：首次啟動自動產生

如果您在執行 `docker-compose up` 時**沒有**建立 `.env` 檔案，應用程式將會自動為您產生一個主金鑰，並將其顯示在終端機的日誌中。您可以複製這個金鑰，並依照步驟一的說明將它儲存到您的 `.env` 檔案中，以供未來部署使用。

### 關於資料持久化

`docker-compose.yml` 檔案已設定將本地的 `./api_keys.txt` 檔案掛載為 volume。這可以確保您透過管理頁面產生的所有使用者 API 金鑰，都會被保存在您的主機上，並在容器重啟後依然存在。

## 使用說明

### 1. 產生使用者 API 金鑰

-   前往 `http://localhost:8000/admin`。
-   輸入您在 `.env` 檔案中設定的**主金鑰**。金鑰會被儲存在您的瀏覽器 session 中，在分頁關閉前都無須重新輸入。
-   點擊「產生新金鑰」來建立一個使用者級別的 API 金鑰。複製此金鑰以供後續步驟使用。

### 2. 使用服務

-   **即時日誌檢視器 & MQTT 設定**：前往 `http://localhost:8000/` 或 `/settings`。如果您尚未輸入金鑰，頁面會提示您輸入一個**使用者 API 金鑰**。此金鑰同樣會被記在瀏覽器 session 中，在同一個分頁中切換頁面不需重新輸入。
-   **MQTT 與事件 API**：當呼叫像 `/api/config-mqtt` 或 `/api/status` 這樣的端點時，請在 Authorization 標頭中附上**使用者 API 金鑰**：
    ```bash
    curl -X POST http://localhost:8000/api/config-mqtt \
         -H "Authorization: Bearer YOUR_USER_API_KEY" \
         -d '{...}'
    ```
-   **地圖下載 API**：這些端點使用的是 **Nuwa RMS Token**，而非本服務的使用者金鑰。
    ```bash
    curl -X POST http://localhost:8000/trigger-refresh \
         -H "Authorization: Bearer YOUR_NUWA_API_TOKEN"
    ```

## API 端點

-   `GET /`: 主要日誌檢視器 UI。
-   `GET /admin`: 金鑰管理頁面。
-   `POST /api/admin/generate-key`: (管理員) 產生新的使用者金鑰。
-   `POST /api/admin/revoke-key`: (管理員) 撤銷使用者金鑰。
-   `GET /api/admin/keys`: (管理員) 列出所有使用者金鑰。
-   `POST /api/config-mqtt`: (使用者) 設定 MQTT 連線。
-   `POST /api/{event_type}`: (使用者) 發布事件。
-   `WS /ws`: (使用者) 用於日誌串流的 WebSocket。
-   `POST /trigger-refresh`: (Nuwa Token) 觸發地圖下載。
-   `GET /field-map`: (Nuwa Token) 獲取地圖資料。
-   `GET /health`: 健康檢查。

## 專案結構

```
.
├── app/
│   ├── auth.py             # 驗證與金鑰管理邏輯
│   ├── main.py             # FastAPI 應用程式、API 端點
│   ├── map_downloader.py   # 獲取地圖資料的邏輯
│   └── templates/
│       └── admin.html      # 管理頁面的 HTML/JS
├── api_keys.txt            # 儲存使用者 API 金鑰
├── docker-compose.yml      # Docker Compose 設定
├── Dockerfile              # 用於建置映像檔的說明
├── entrypoint.sh           # 用於金鑰產生的啟動腳本
├── .env                    # 環境變數檔案 (例如 MASTER_KEY)
└── requirements.txt        # Python 依賴套件
```
