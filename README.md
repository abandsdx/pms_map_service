# Nuwa Map and Log Service

## Overview

This application serves as a bridge and utility tool for interacting with Nuwa Robotics services. It performs two primary functions:

1.  **Map Data Downloader**: It fetches map data and images from the Nuwa Robotics Mission (RMS) API, processes them, and serves them through a local API.
2.  **Real-time Log Viewer**: It connects to an MQTT broker to receive and send robot-related events, displaying them in real-time on a web interface.

The application is built with FastAPI and is designed to be run with Docker.

## Features

-   **Dynamic Map Fetching**: Trigger a background task to download and parse the latest map data from the Nuwa RMS API.
-   **Data Persistence**: Map images and processed JSON data are stored on a local volume to prevent data loss on container restart.
-   **Segregated Outputs**: Handles multiple API tokens by storing map data in separate directories based on a hash of the token.
-   **Real-time Event/Log Monitoring**: A WebSocket-based web UI for viewing live logs from an MQTT message broker.
-   **MQTT Configuration**: Dynamically configure the MQTT broker connection (Host, Port, Topics, Credentials) through the web UI.
-   **RESTful API**: A set of API endpoints to trigger actions, retrieve data, and post events.
-   **Containerized**: Easy to deploy and run using Docker and Docker Compose.

## Architecture

The system consists of a single service:

-   **FastAPI Server (`main.py`)**: This is the core of the application. It serves the web UI, handles HTTP requests, manages the WebSocket connection for live logs, and communicates with the MQTT broker.
-   **Map Downloader (`map_downloader.py`)**: A module triggered via an API call. It communicates with the external Nuwa RMS API to download raw map data (zip files), extracts them, parses metadata from YAML files (`map.yaml`, `location.yaml`), and saves the final map images (`.jpg`) and a structured JSON file in the `outputs` directory.
-   **MQTT Broker (External)**: The application is a client to an MQTT broker. It subscribes to a topic to receive messages and publishes messages sent via the API. The broker itself is not included in the `docker-compose.yml` and must be provided externally.

## Prerequisites

-   [Docker](https://www.docker.com/get-started)
-   [Docker Compose](https://docs.docker.com/compose/install/)

## Getting Started

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Build and run the container:**
    Use Docker Compose to build the image and start the service.
    ```bash
    docker-compose up -d
    ```
    The server will be running and accessible at `http://localhost:8000`.

## Usage

### 1. Download Map Data

To download and process map data, you need a valid API token from Nuwa Robotics.

-   **Send a POST request** to the `/trigger-refresh` endpoint with your token in the `Authorization` header.

    **Example using `curl`:**
    ```bash
    curl -X POST http://localhost:8000/trigger-refresh \
         -H "Authorization: Bearer YOUR_NUWA_API_TOKEN"
    ```
    This will start a background task on the server to download, process, and save the map data.

### 2. Access Processed Map Data

Once the background task from the previous step is complete, you can retrieve the processed data.

-   **Get the JSON data**: Send a GET request to the `/field-map` endpoint. You must provide the same token used to trigger the refresh.

    **Example using `curl`:**
    ```bash
    curl -X GET http://localhost:8000/field-map \
         -H "Authorization: Bearer YOUR_NUWA_API_TOKEN"
    ```
    This returns a JSON object containing structured information about all fields and maps, including location coordinates.

-   **Access Map Images**: The map images (`.jpg`) are served statically. The URL path is constructed from the token hash and the image filename. The exact path can be found in the `mapImage` field of the JSON response from the `/field-map` endpoint. The image URL will look something like this:
    `http://localhost:8000/<token_hash>_maps/<image_filename>.jpg`

### 3. Real-time Log Viewer & MQTT

-   **Open the Web UI**: Navigate to `http://localhost:8000` in your web browser.
-   **Configure MQTT**: Use the "MQTT 設定" form to enter the details of your MQTT broker (host, port, topics, credentials) and click "套用" (Apply). The connection status will be displayed.
-   **View Logs**: Once connected, the application will subscribe to the specified "訂閱 Topic" (Subscribe Topic). Any messages published to that topic will appear in the "即時Log" section.
-   **Publish Events**: You can use the API endpoints (`/api/status`, `/api/arrival`, etc.) to publish messages to the corresponding topics on the broker.

## API Endpoints

-   `POST /trigger-refresh`: Starts the map download and processing task. Requires `Authorization` header.
-   `GET /field-map`: Returns the processed map data in JSON format. Requires `Authorization` header.
-   `POST /api/config-mqtt`: Configures and connects to the MQTT broker.
-   `POST /api/{arrival|status|exception|control}`: Publishes a JSON payload to the corresponding MQTT topic.
-   `GET /`: Serves the HTML web interface.
-   `GET /health`: Health check endpoint.
-   `WS /ws`: WebSocket endpoint for real-time log streaming to the UI.

## Project Structure

```
.
├── app/
│   ├── main.py           # FastAPI application, API endpoints, WebSocket logic
│   └── map_downloader.py # Logic for fetching and processing map data
├── outputs/              # Persisted storage for downloaded maps and JSON files (mounted as a volume)
├── Dockerfile            # Instructions for building the Docker image
├── docker-compose.yml    # Docker Compose configuration for running the service
└── requirements.txt      # Python dependencies
```

---

# Nuwa 地圖與日誌服務

## 總覽

本應用程式作為一個橋樑與工具，用於和女媧機器人 (Nuwa Robotics) 的服務進行互動。它主要有兩個功能：

1.  **地圖資料下載器**：從女媧機器人任務系統 (RMS) API 獲取地圖資料與圖片，進行處理後，透過本地 API 提供服務。
2.  **即時日誌檢視器**：連接到一個 MQTT 代理 (broker)，以接收和發送與機器人相關的事件，並在網頁介面上即時顯示。

本應用程式使用 FastAPI 框架開發，並設計為在 Docker 環境中運行。

## 功能特性

-   **動態地圖獲取**：觸發背景任務，從 Nuwa RMS API 下載並解析最新的地圖資料。
-   **資料持久化**：地圖圖片和處理後的 JSON 資料會儲存在本地 volume 中，以防止容器重啟時資料遺失。
-   **獨立輸出目錄**：根據 API token 的雜湊值，將不同 token 的地圖資料儲存在各自獨立的目錄中，以支援多使用者。
-   **即時事件/日誌監控**：基於 WebSocket 的網頁介面，用於檢視來自 MQTT 代理的即時日誌。
-   **MQTT 動態設定**：透過網頁介面動態設定 MQTT 代理的連線資訊（主機、埠、主題、憑證）。
-   **RESTful API**：提供一組 API 端點，用於觸發動作、獲取資料和發布事件。
-   **容器化**：使用 Docker 和 Docker Compose，易於部署和運行。

## 系統架構

本系統包含單一服務：

-   **FastAPI 伺服器 (`main.py`)**：此為應用程式的核心。它提供網頁介面、處理 HTTP 請求、管理用於即時日誌的 WebSocket 連線，並與 MQTT 代理通訊。
-   **地圖下載器 (`map_downloader.py`)**：此模組透過 API 呼叫觸發。它與外部的 Nuwa RMS API 通訊，下載原始地圖資料（zip 檔案），解壓縮後從 YAML 檔案（`map.yaml`, `location.yaml`）中解析元數據，並將最終的地圖圖片（`.jpg`）和結構化的 JSON 檔案儲存於 `outputs` 目錄。
-   **MQTT 代理 (外部)**：本應用程式作為 MQTT 代理的客戶端。它訂閱一個主題以接收訊息，並發布透過 API 傳送的訊息。代理本身不包含在 `docker-compose.yml` 中，必須由外部提供。

## 環境要求

-   [Docker](https://www.docker.com/get-started)
-   [Docker Compose](https://docs.docker.com/compose/install/)

## 開始使用

1.  **複製專案原始碼：**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **建置並運行容器：**
    使用 Docker Compose 來建置映像檔並啟動服務。
    ```bash
    docker-compose up -d
    ```
    伺服器將會啟動並運行在 `http://localhost:8000`。

## 使用說明

### 1. 下載地圖資料

要下載並處理地圖資料，您需要一組有效的 Nuwa Robotics API token。

-   **發送 POST 請求** 到 `/trigger-refresh` 端點，並將您的 token 放在 `Authorization` 標頭中。

    **`curl` 範例：**
    ```bash
    curl -X POST http://localhost:8000/trigger-refresh \
         -H "Authorization: Bearer YOUR_NUWA_API_TOKEN"
    ```
    這將在伺服器上啟動一個背景任務，以下載、處理並儲存地圖資料。

### 2. 存取處理後的地圖資料

當上一步的背景任務完成後，您便可以獲取處理後的資料。

-   **獲取 JSON 資料**：發送 GET 請求到 `/field-map` 端點。您必須提供與觸發刷新時相同的 token。

    **`curl` 範例：**
    ```bash
    curl -X GET http://localhost:8000/field-map \
         -H "Authorization: Bearer YOUR_NUWA_API_TOKEN"
    ```
    這會回傳一個 JSON 物件，其中包含所有場域和地圖的結構化資訊，包括地點座標。

-   **存取地圖圖片**：地圖圖片 (`.jpg`) 是以靜態檔案的形式提供。其 URL 路徑由 token 雜湊值和圖片檔名組成。確切的路徑可以在 `/field-map` 端點回傳的 JSON 中的 `mapImage` 欄位找到。圖片 URL 的格式如下：
    `http://localhost:8000/<token_hash>_maps/<image_filename>.jpg`

### 3. 即時日誌檢視器 & MQTT

-   **開啟網頁介面**：在您的瀏覽器中前往 `http://localhost:8000`。
-   **設定 MQTT**：使用「MQTT 設定」表單來輸入您的 MQTT 代理資訊（主機、埠、主題、憑證），然後點擊「套用」。連線狀態將會顯示在頁面上。
-   **檢視日誌**：一旦連線成功，應用程式將訂閱指定的「訂閱 Topic」。任何發布到該主題的訊息都會出現在「即時Log」區塊中。
-   **發布事件**：您可以使用 API 端點（`/api/status`, `/api/arrival` 等）來將訊息發布到代理上對應的主題。

## API 端點

-   `POST /trigger-refresh`：啟動地圖下載與處理任務。需要 `Authorization` 標頭。
-   `GET /field-map`：以 JSON 格式回傳處理後的地圖資料。需要 `Authorization` 標頭。
-   `POST /api/config-mqtt`：設定並連接到 MQTT 代理。
-   `POST /api/{arrival|status|exception|control}`：將 JSON 資料發布到對應的 MQTT 主題。
-   `GET /`：提供 HTML 網頁介面。
-   `GET /health`：健康檢查端點。
-   `WS /ws`：用於將即時日誌串流到 UI 的 WebSocket 端點。

## 專案結構

```
.
├── app/
│   ├── main.py           # FastAPI 應用程式、API 端點、WebSocket 邏輯
│   └── map_downloader.py # 獲取與處理地圖資料的邏輯
├── outputs/              # 用於儲存下載的地圖和 JSON 檔案的持久化目錄 (以 volume 形式掛載)
├── Dockerfile            # 用於建置 Docker 映像檔的說明
├── docker-compose.yml    # 用於運行服務的 Docker Compose 設定
└── requirements.txt      # Python 依賴套件
```
