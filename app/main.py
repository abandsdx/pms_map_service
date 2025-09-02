import os
import asyncio
import json
import secrets
from datetime import datetime
from typing import List

from fastapi import (
    FastAPI, BackgroundTasks, Header, HTTPException, Depends,
    WebSocket, WebSocketDisconnect, Request, Query
)
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

import paho.mqtt.client as mqtt

# === Custom Modules ===
from app.map_downloader import download_and_parse_maps, get_token_hash
from app.auth import key_manager

app = FastAPI(title="Nuwa Map and Log Service")
OUTPUT_DIR = "outputs"
mounted_folders = set()

# Setup Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# === MQTT & WebSocket State ===
clients: List[WebSocket] = []
clients_lock = asyncio.Lock()
mqtt_client = None
mqtt_connected = False
mqtt_incoming_queue = asyncio.Queue()

# === Status Code Mapping ===
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

# === MQTT Default Config ===
mqtt_config = {
    "host": "localhost", "port": 1883, "username": "", "password": "",
    "subscribe_topic": "robot/events", "publish_topic": "robot/events",
    "topics_by_type": {
        "arrival": "robot/arrival", "status": "robot/status",
        "exception": "robot/exception", "control": "robot/control"
    }
}

# === Authentication Dependencies ===
def get_token_from_header(authorization: str = Header(..., alias="Authorization")):
    """Extracts token from 'Bearer <token>' header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format. Must be 'Bearer <token>'.")
    return authorization[7:]

def verify_user_token(token: str = Depends(get_token_from_header)):
    """Dependency to verify a user-level API key."""
    if not key_manager.is_valid_user_key(token):
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid or expired user key.")

def verify_master_key(token: str = Depends(get_token_from_header)):
    """Dependency to verify the master key for admin routes."""
    if not key_manager.is_valid_master_key(token):
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid master key.")

# === Admin APIs for Key Management ===
class RevokeKeyRequest(BaseModel):
    key_to_revoke: str

@app.get("/api/admin/keys", tags=["Admin"])
def list_user_keys(admin_auth: None = Depends(verify_master_key)):
    """Lists all current user API keys."""
    return {"user_keys": key_manager.get_all_user_keys()}

@app.post("/api/admin/generate-key", tags=["Admin"])
def generate_user_key(admin_auth: None = Depends(verify_master_key)):
    """Generates a new user API key, adds it to the store, and returns it."""
    new_key = secrets.token_hex(16)
    if key_manager.add_key(new_key):
        return {"status": "success", "new_key": new_key}
    raise HTTPException(status_code=500, detail="Failed to add new key to key file.")

@app.post("/api/admin/revoke-key", tags=["Admin"])
def revoke_user_key(request: RevokeKeyRequest, admin_auth: None = Depends(verify_master_key)):
    """Revokes an existing user API key."""
    if key_manager.revoke_key(request.key_to_revoke):
        return {"status": "success", "revoked_key": request.key_to_revoke}
    raise HTTPException(status_code=404, detail="Key not found or failed to revoke key.")

# === Static Folder Mounting ===
def mount_static_folder(folder_name: str):
    if folder_name in mounted_folders:
        return
    folder_path = os.path.join(OUTPUT_DIR, folder_name)
    if os.path.isdir(folder_path):
        app.mount(f"/{folder_name}", StaticFiles(directory=folder_path), name=folder_name)
        mounted_folders.add(folder_name)
        print(f"✅ Dynamically mounted /{folder_name} => {folder_path}")

# === Map Download APIs ===
@app.post("/trigger-refresh", tags=["Maps"])
def trigger_refresh(background_tasks: BackgroundTasks, authorization: str = Header(None)):
    """Triggers a background task to download map data using a Nuwa RMS token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Nuwa RMS Authorization header.")
    token_hash = get_token_hash(authorization)
    background_tasks.add_task(download_and_parse_maps, authorization)
    background_tasks.add_task(mount_static_folder, f"{token_hash}_maps")
    return {"status": "processing", "message": "Map update and mounting initiated."}

@app.get("/field-map", tags=["Maps"])
def get_map_file(authorization: str = Header(None)):
    """Retrieves the processed JSON map file for a given Nuwa RMS token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Nuwa RMS Authorization header.")
    token_hash = get_token_hash(authorization)
    json_file_path = os.path.join(OUTPUT_DIR, f"field_map_r_locations_{token_hash}.json")
    if not os.path.exists(json_file_path):
        return JSONResponse(status_code=404, content={"error": "JSON file not found. Please trigger /trigger-refresh first."})
    return FileResponse(json_file_path, media_type="application/json")

# === MQTT & WebSocket Logic ===
def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {"raw_payload": msg.payload.hex()}
    asyncio.run(mqtt_incoming_queue.put({"type": "mqtt", "data": data}))

@app.on_event("startup")
async def startup_event():
    async def mqtt_loop():
        while True:
            data = await mqtt_incoming_queue.get()
            await broadcast_log(data)
    asyncio.create_task(mqtt_loop())

async def broadcast_log(data: dict):
    # ... (rest of broadcast logic is unchanged)
    status_code = data["data"].get("status")
    if status_code and status_code in STATUS_MAPPING:
        data["data"]["statusText"] = STATUS_MAPPING[status_code]
    if "timestamp" in data["data"]:
        try:
            ts = int(data["data"]["timestamp"])
            data["_log_prefix"] = datetime.fromtimestamp(ts).strftime("[%Y/%-m/%-d %p%-I:%M:%S]")
        except (ValueError, TypeError):
            data["_log_prefix"] = "[Invalid Timestamp]"
    if mqtt_connected:
        topic = mqtt_config["topics_by_type"].get(data.get("type"), mqtt_config["publish_topic"])
        mqtt_client.publish(topic, json.dumps(data))

    to_remove = []
    async with clients_lock:
        for client in clients:
            try:
                await client.send_json(data)
            except WebSocketDisconnect:
                to_remove.append(client)
            except Exception as e:
                print(f"Error sending to client: {e}")
                to_remove.append(client)
        for client in to_remove:
            clients.remove(client)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for real-time log streaming."""
    if not key_manager.is_valid_user_key(token):
        await websocket.close(code=4001)
        return
    await websocket.accept()
    async with clients_lock:
        clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass  # Client disconnected, expected behavior
    finally:
        async with clients_lock:
            if websocket in clients:
                clients.remove(websocket)

# === MQTT Configuration API ===
@app.post("/api/config-mqtt", tags=["MQTT"])
async def config_mqtt(request: Request, auth: None = Depends(verify_user_token)):
    global mqtt_client, mqtt_connected
    config = await request.json()
    # ... (rest of MQTT config logic is largely unchanged)
    topics_by_type = config.get("topics_by_type")
    if topics_by_type:
        mqtt_config["topics_by_type"].update(topics_by_type)
        config.pop("topics_by_type")
    mqtt_config.update(config)
    if mqtt_client:
        try:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
        except: pass
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

# === Event Handling APIs ===
@app.post("/api/{event_type}", tags=["Events"])
async def handle_event(event_type: str, request: Request, auth: None = Depends(verify_user_token)):
    """Handles arrival, status, exception, and control events."""
    if event_type not in ["arrival", "status", "exception", "control"]:
        raise HTTPException(status_code=404, detail="Invalid event type.")
    payload = await request.json()
    data = {"type": event_type, "data": payload}
    await broadcast_log(data)
    return {"status": "ok"}

# === Frontend & Docs ===
@app.get("/admin", response_class=HTMLResponse, tags=["Frontend"])
async def get_admin_page(request: Request):
    """Serves the admin page for key management."""
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def get_combined_ui():
    topics_inputs = "".join([
        f"<label>{key.capitalize()} Topic:</label><br><input type='text' id='mqttTopic_{key}' value='{topic}'><br><br>\n"
        for key, topic in mqtt_config["topics_by_type"].items()
    ])
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset='UTF-8'>
    <title>📡 Real-time Log Viewer</title>
    <style>
        body {{ font-family: sans-serif; background: #f0f0f0; padding: 20px; }}
        .section {{ margin-bottom: 30px; }}
        .log {{ background: #fff; border: 1px solid #ddd; padding: 10px; height: 300px; overflow-y: auto; }}
        .form-grid {{ display: flex; gap: 40px; }}
        /* ... other styles ... */
    </style>
</head>
<body>
    <h1>📄 Real-time Log Viewer</h1>
    <div class='log' id='log'></div>

    <h2>⚙️ MQTT Configuration</h2>
    <form id='mqttForm'>
        <!-- ... form content ... -->
        {topics_inputs}
        <button type='submit'>Apply</button>
    </form>
    <div>Connection Status: <span id='mqttStatus'>Not Configured</span></div>

    <script>
        const token = prompt("Please enter your API Key:");
        if (!token) {{
            alert("API Key is required to connect.");
            document.body.innerHTML = "API Key required.";
        }} else {{
            const log = document.getElementById('log');
            const mqttForm = document.getElementById('mqttForm');
            const mqttStatus = document.getElementById('mqttStatus');
            const ws = new WebSocket(`${{location.protocol === 'https:' ? 'wss:' : 'ws:'}}//${{location.host}}/ws?token=${{token}}`);

            ws.onopen = () => {{ mqttStatus.textContent = "WebSocket connected. Configure MQTT to see logs."; }};
            ws.onmessage = (event) => {{
                // ... message handling logic ...
            }};
            ws.onerror = (e) => {{ mqttStatus.textContent = "❌ WebSocket connection error."; }};
            ws.onclose = (e) => {{
                if (e.code === 4001) {{
                    mqttStatus.textContent = "❌ WebSocket disconnected: Invalid API Key.";
                }} else {{
                    mqttStatus.textContent = "❌ WebSocket disconnected.";
                }}
            }};

            mqttForm.onsubmit = async (e) => {{
                e.preventDefault();
                // ... form submission logic ...
                const res = await fetch("/api/config-mqtt", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json", "Authorization": `Bearer ${{token}}` }},
                    body: JSON.stringify(body)
                }});
                const result = await res.json();
                mqttStatus.textContent = result.status === "connected" ? "✅ MQTT Connected" : `❌ MQTT Error: ${{result.detail}}`;
            }};
        }}
    </script>
</body>
</html>
"""

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "OK", "message": "Server is running."}

@app.get("/api-docs.md", response_class=HTMLResponse, tags=["Docs"])
async def get_markdown_docs():
    # ... (unchanged)
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    md = [f"# {schema['info']['title']} API", f"Version: {schema['info']['version']}", ""]
    # ...
    return "\n".join(md)
