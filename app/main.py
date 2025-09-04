import os
import asyncio
import json
from datetime import datetime
from typing import List
from fastapi.responses import HTMLResponse
from fastapi import Request

from fastapi import (
    FastAPI, BackgroundTasks, Header, HTTPException, Depends,
    WebSocket, WebSocketDisconnect, Request, Query
)
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi

import paho.mqtt.client as mqtt

# === 自定義模組 ===
from app.map_downloader import download_and_parse_maps, get_token_hash

app = FastAPI()
OUTPUT_DIR = "outputs"
mounted_folders = set()  # 記錄已掛載的資料夾，避免重複掛載

# === MQTT 與 WebSocket 狀態 ===
clients: List[WebSocket] = []
clients_lock = asyncio.Lock()
mqtt_client = None
mqtt_connected = False
mqtt_incoming_queue = asyncio.Queue()

# === 驗證設定 ===
SECRET_TOKEN = "nuwa8888"
STATUS_MAPPING = {
    "ST-M1001": "收到任務申請",
    "ST-M1002": "新建調度任務",
    "ST-M1003": "到達取貨點",
    "ST-M1004": "送物點到達",
    "ST-M1005": "達成額外結束條件",
    "ST-M1006": "任務結束",
    "ST-M1007": "任務結束(使用者退件)",
    "ST-M1008": "任務結束返回",
    "ST-M1009": "到點通知",
    "ST-M1010": "任務結束返回-已返回待命點",
    "ST-N1001": "通知住戶",
    "ST-N1002": "等待住戶",
    "ST-N1003": "住戶取物中",
    "ST-EL1001": "[EL電梯] 已從某樓進入電梯",
    "ST-EL1002": "[EL電梯] 已出電梯至某樓層",
    "ST-VM1001": "[VM智販機] 已到達智販機取物",
    "ST-VM1002": "[VM智販機] 已完成智販機取物",
}

mqtt_config = {
    "host": "localhost",
    "port": 1883,
    "username": "",
    "password": "",
    "subscribe_topic": "robot/events",
    "publish_topic": "robot/events",
    "topics_by_type": {
        "arrival": "robot/arrival",
        "status": "robot/status",
        "exception": "robot/exception",
        "control": "robot/control"
    }
}

# === 通用驗證 ===
def verify_token(authorization: str = Header(..., alias="Authorization")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format")
    token = authorization[7:]
    if token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Unauthorized")

# === 掛載資料夾 ===
def mount_static_folder(folder_name: str):
    if folder_name in mounted_folders:
        return
    folder_path = os.path.join(OUTPUT_DIR, folder_name)
    if os.path.isdir(folder_path):
        app.mount(f"/{folder_name}", StaticFiles(directory=folder_path), name=folder_name)
        mounted_folders.add(folder_name)
        print(f"✅ 動態掛載 /{folder_name} => {folder_path}")

# === 地圖下載觸發 API ===
@app.post("/trigger-refresh")
def trigger_refresh(background_tasks: BackgroundTasks, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token_hash = get_token_hash(authorization)

    def task():
        download_and_parse_maps(authorization)
        mount_static_folder(f"{token_hash}_maps")

    background_tasks.add_task(task)
    return {"status": "processing", "message": "地圖更新與掛載中"}

# === 地圖 JSON 下載 API ===
@app.get("/field-map")
def get_map_file(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token_hash = get_token_hash(authorization)
    json_file_path = os.path.join(OUTPUT_DIR, f"field_map_r_locations_{token_hash}.json")
    if not os.path.exists(json_file_path):
        return JSONResponse(status_code=404, content={"error": "尚未產生 JSON，請先觸發 /trigger-refresh"})
    return FileResponse(json_file_path, media_type="application/json", filename=f"field_map_r_locations_{token_hash}.json")

# === MQTT 初始化與訊息處理 ===
def on_mqtt_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    try:
        data = json.loads(payload)
    except:
        data = {"raw": payload}
    asyncio.create_task(mqtt_incoming_queue.put({"type": "mqtt", "data": data}))

@app.on_event("startup")
async def startup_event():
    async def mqtt_loop():
        while True:
            data = await mqtt_incoming_queue.get()
            await broadcast_log(data)
    asyncio.create_task(mqtt_loop())

# === 廣播訊息給前端 WebSocket 與 MQTT publish ===
async def broadcast_log(data: dict):
    status_code = data["data"].get("status")
    if status_code and status_code in STATUS_MAPPING:
        data["data"]["statusText"] = STATUS_MAPPING[status_code]

    if "timestamp" in data["data"]:
        try:
            ts = int(data["data"]["timestamp"])
            log_time = datetime.fromtimestamp(ts).strftime("[%Y/%-m/%-d %p%-I:%M:%S]")
            data["_log_prefix"] = log_time
        except:
            data["_log_prefix"] = "[時間錯誤]"

    if mqtt_connected:
        topic = mqtt_config["topics_by_type"].get(data.get("type"), mqtt_config["publish_topic"])
        mqtt_client.publish(topic, json.dumps(data))

    to_remove = []
    async with clients_lock:
        for client in clients:
            try:
                await client.send_json(data)
            except:
                to_remove.append(client)
        for client in to_remove:
            clients.remove(client)

# === WebSocket endpoint ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    if token != SECRET_TOKEN:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    async with clients_lock:
        clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        async with clients_lock:
            clients.remove(websocket)
    except:
        async with clients_lock:
            clients.remove(websocket)

# === MQTT 設定 API ===
@app.post("/api/config-mqtt")
async def config_mqtt(request: Request, auth=Depends(verify_token)):
    global mqtt_client, mqtt_connected
    config = await request.json()

    topics_by_type = config.get("topics_by_type")
    if topics_by_type:
        mqtt_config["topics_by_type"].update(topics_by_type)
        config.pop("topics_by_type")
    mqtt_config.update(config)

    if mqtt_client:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except:
            pass

    mqtt_client = mqtt.Client()
    mqtt_client.on_message = on_mqtt_message
    if mqtt_config["username"] and mqtt_config["password"]:
        mqtt_client.username_pw_set(mqtt_config["username"], mqtt_config["password"])

    try:
        mqtt_client.connect(mqtt_config["host"], mqtt_config["port"], 60)
        mqtt_client.subscribe(mqtt_config["subscribe_topic"])
        mqtt_client.loop_start()
        mqtt_connected = True
        return {"status": "connected", "config": mqtt_config}
    except Exception as e:
        mqtt_connected = False
        return {"status": "error", "detail": str(e)}

# === 各事件處理 API ===
@app.post("/api/arrival")
@app.post("/api/status")
@app.post("/api/exception")
@app.post("/api/control")
async def handle_event(request: Request, auth=Depends(verify_token)):
    payload = await request.json()
    path = request.url.path
    event_type = path.split("/")[-1]
    data = {"type": event_type, "data": payload}
    await broadcast_log(data)
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def get_combined_ui():
    topics_inputs = ""
    for key, topic in mqtt_config["topics_by_type"].items():
        topics_inputs += f"<label>{key.capitalize()} Topic:</label><br><input type='text' id='mqttTopic_{key}' value='{topic}'><br><br>\n"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset='UTF-8'>
    <title>📡 即時Log</title>
    <style>
        body {{ font-family: sans-serif; background: #f0f0f0; padding: 20px; }}
        .section {{ margin-bottom: 30px; }}
        .log {{ background: #fff; border: 1px solid #ddd; padding: 10px; height: 300px; overflow-y: auto; }}
        .log-entry {{ margin-bottom: 10px; }}
        .arrival {{ color: green; }}
        .status {{ color: blue; }}
        .exception {{ color: red; }}
        .control {{ color: orange; }}
        .form-grid {{ display: flex; gap: 40px; }}
    </style>
</head>
<body>
    <div class='section'>
        <h1>📄即時Log（發送與接收）</h1>
        <div class='log' id='log'></div>
    </div>

    <div class='section'>
        <h2>⚙️ MQTT 設定</h2>
        <form id='mqttForm'>
            <div class='form-grid'>
                <div>
                    <label>Host:</label><br>
                    <input type='text' id='mqttHost' value='{mqtt_config["host"]}'><br><br>
                    <label>Port:</label><br>
                    <input type='number' id='mqttPort' value='{mqtt_config["port"]}'><br><br>
                    <label>訂閱 Topic:</label><br>
                    <input type='text' id='mqttSub' value='{mqtt_config["subscribe_topic"]}'><br><br>
                    <label>發送 Topic(預設):</label><br>
                    <input type='text' id='mqttPub' value='{mqtt_config["publish_topic"]}'><br><br>
                    <label>Username:</label><br>
                    <input type='text' id='mqttUser' value='{mqtt_config["username"]}'><br><br>
                    <label>Password:</label><br>
                    <input type='password' id='mqttPass' value='{mqtt_config["password"]}'><br>
                </div>
                <div>
                    {topics_inputs}
                </div>
            </div>
            <br>
            <button type='submit'>套用</button>
        </form>
        <div>連線狀態：<span id='mqttStatus'>尚未設定</span></div>
    </div>

    <script>
        const token = "nuwa8888";
        const log = document.getElementById('log');
        const mqttForm = document.getElementById('mqttForm');
        const mqttStatus = document.getElementById('mqttStatus');

        const ws = new WebSocket("ws://" + location.host + "/ws?token=" + token);

        ws.onmessage = (event) => {{
            const message = JSON.parse(event.data);
            const entry = document.createElement("div");
            entry.classList.add("log-entry");
            entry.classList.add(message.type);

            let logTime = new Date().toLocaleString();
            if (message.data && message.data.timestamp) {{
                try {{
                    const ts = parseInt(message.data.timestamp);
                    if (!isNaN(ts)) {{
                        logTime = new Date(ts * 1000).toLocaleString();
                    }}
                }} catch (e) {{
                    console.warn("timestamp parse error", e);
                }}
            }}

            entry.innerHTML = `[${{logTime}}] [${{message.type.toUpperCase()}}] <pre>${{JSON.stringify(message.data, null, 2)}}</pre>`;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }};

        ws.onerror = (e) => {{
            console.error("WebSocket error:", e);
            mqttStatus.textContent = "❌ WebSocket 連線錯誤";
        }};

        ws.onclose = (e) => {{
            console.warn("WebSocket closed:", e);
            mqttStatus.textContent = "❌ WebSocket 已斷線";
        }};

        mqttForm.onsubmit = async (e) => {{
            e.preventDefault();
            const topics_by_type = {{
                arrival: document.getElementById("mqttTopic_arrival").value,
                status: document.getElementById("mqttTopic_status").value,
                exception: document.getElementById("mqttTopic_exception").value,
                control: document.getElementById("mqttTopic_control").value
            }};
            const body = {{
                host: document.getElementById("mqttHost").value,
                port: parseInt(document.getElementById("mqttPort").value),
                subscribe_topic: document.getElementById("mqttSub").value,
                publish_topic: document.getElementById("mqttPub").value,
                username: document.getElementById("mqttUser").value,
                password: document.getElementById("mqttPass").value,
                topics_by_type: topics_by_type
            }};
            const res = await fetch("/api/config-mqtt", {{
                method: "POST",
                headers: {{
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token
                }},
                body: JSON.stringify(body)
            }});
            const result = await res.json();
            mqttStatus.textContent = result.status === "connected" ? "✅ 連線成功" : "❌ 錯誤: " + result.detail;
        }};
    </script>
</body>
</html>
"""
# === 健康檢查 ===
@app.get("/health")
def health_check():
    return {"status": "OK", "message": "伺服器正常運作中"}

# === Markdown 產生文件 ===
@app.get("/api-docs.md", response_class=HTMLResponse)
async def get_markdown_docs():
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    md = [f"# {schema['info']['title']} API", f"版本: {schema['info']['version']}", ""]
    for path, methods in schema["paths"].items():
        for method, info in methods.items():
            md.append(f"## `{method.upper()}` {path}\n{info.get('summary', '')}\n")
            if "requestBody" in info:
                content = info["requestBody"]["content"].get("application/json", {})
                schema_ = content.get("schema", {})
                md.append("### Request Body:")
                md.append("```json\n" + str(schema_) + "\n```")
    return "\n".join(md)
