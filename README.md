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

1.  **複製專案原始碼：**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **首次啟動與主金鑰設定：**
    使用 Docker Compose 來建置映像檔並啟動服務。
    ```bash
    docker-compose up
    ```
    在首次運行時，服務會偵測到 `MASTER_KEY` 尚未設定，因此會自動產生一個新的，並在您的終端機日誌中用一個顯眼的區塊印出。

    **請在日誌中尋找以下訊息：**
    ```
    #####################################################################
    #  警告：未偵測到 MASTER_KEY 環境變數。                             #
    #  您的主金鑰是：                                                   #
    #      some_long_randomly_generated_hex_string                        #
    #  請將此金鑰加入到您的 docker-compose.yml 檔案中...                #
    #####################################################################
    ```

3.  **設定主金鑰：**
    -   從日誌中複製那個自動產生的主金鑰。
    -   停止服務 (`Ctrl+C`)。
    -   打開 `docker-compose.yml` 檔案，並用您複製的金鑰來設定 `MASTER_KEY` 環境變數。
        ```yaml
        services:
          fastapi-server:
            environment:
              - MASTER_KEY=your_super_secret_master_key # 在此貼上您的金鑰
        ```
    -   儲存檔案。

4.  **以分離模式運行：**
    現在金鑰已設定完成，您可以在背景模式下運行服務。
    ```bash
    docker-compose up -d
    ```

## 使用說明

### 1. 產生使用者 API 金鑰

-   前往 `http://localhost:8000/admin`。
-   輸入您在 `docker-compose.yml` 中設定的**主金鑰**。金鑰會被儲存在您的瀏覽器 session 中，在分頁關閉前都無須重新輸入。
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
└── requirements.txt        # Python 依賴套件
```
