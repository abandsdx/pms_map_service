import os
import asyncio
import json
import secrets
from datetime import datetime
from typing import List, Dict, Set

from fastapi import (
    FastAPI, BackgroundTasks, Header, HTTPException, Depends,
    WebSocket, WebSocketDisconnect, Request, Query
)
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# === Custom Modules ===
from app.map_downloader import download_and_parse_maps, get_token_hash
from app.auth import key_manager
from app.mqtt_manager import ConnectionManager

app = FastAPI(title="Nuwa Map and Log Service")
# Define project root and ensure OUTPUT_DIR is an absolute path
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "outputs")
mounted_folders = set()

# Setup Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# === WebSocket Connection Management ===
class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_key: str):
        await websocket.accept()
        async with self.lock:
            if user_key not in self.active_connections:
                self.active_connections[user_key] = set()
            self.active_connections[user_key].add(websocket)

    async def disconnect(self, websocket: WebSocket, user_key: str):
        async with self.lock:
            if user_key in self.active_connections and websocket in self.active_connections[user_key]:
                self.active_connections[user_key].remove(websocket)
                if not self.active_connections[user_key]:
                    del self.active_connections[user_key]

    async def broadcast_to_user(self, user_key: str, data: dict):
        async with self.lock:
            if user_key in self.active_connections:
                for connection in list(self.active_connections[user_key]):
                    try:
                        await connection.send_json(data)
                    except (WebSocketDisconnect, RuntimeError):
                        self.active_connections[user_key].remove(connection)

ws_manager = WebSocketManager()

# === MQTT Message Handling & Broadcasting ===
async def on_mqtt_message_callback(user_key: str, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {"raw_payload": msg.payload.hex()}

    full_message = {"type": "mqtt", "data": data}
    await ws_manager.broadcast_to_user(user_key, full_message)

mqtt_manager = ConnectionManager(config_file="mqtt_configs.json", on_message_callback=on_mqtt_message_callback)

# === Authentication Dependencies ===
def get_token_from_header(authorization: str = Header(..., alias="Authorization")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format. Must be 'Bearer <token>'.")
    return authorization.replace("Bearer ", "")

def verify_user_token(token: str = Depends(get_token_from_header)):
    if not key_manager.is_valid_user_key(token):
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid or expired user key.")
    return token

def verify_master_key(token: str = Depends(get_token_from_header)):
    if not key_manager.is_valid_master_key(token):
        raise HTTPException(status_code=403, detail="Unauthorized: Invalid master key.")
    return token

class LoginRequest(BaseModel):
    key: str

@app.post("/api/login", tags=["Authentication"])
def login(request: LoginRequest):
    key = request.key
    if key_manager.is_valid_master_key(key):
        return {"role": "admin", "token": key}
    if key_manager.is_valid_user_key(key):
        return {"role": "user", "token": key}
    raise HTTPException(status_code=403, detail="Invalid API Key")

# === Admin APIs for Key Management ===
class RevokeKeyRequest(BaseModel):
    key_to_revoke: str

@app.get("/api/admin/keys", tags=["Admin"], dependencies=[Depends(verify_master_key)])
async def list_user_keys():
    return {"user_keys": key_manager.get_all_user_keys()}

@app.post("/api/admin/generate-key", tags=["Admin"], dependencies=[Depends(verify_master_key)])
async def generate_user_key():
    new_key = secrets.token_hex(16)
    if key_manager.add_key(new_key):
        return {"status": "success", "new_key": new_key}
    raise HTTPException(status_code=500, detail="Failed to add new key to key file.")

@app.post("/api/admin/revoke-key", tags=["Admin"], dependencies=[Depends(verify_master_key)])
async def revoke_user_key(request: RevokeKeyRequest):
    if key_manager.revoke_key(request.key_to_revoke):
        return {"status": "success", "revoked_key": request.key_to_revoke}
    raise HTTPException(status_code=404, detail="Key not found or failed to revoke key.")

# === Incoming Data Endpoints ===
class IngestData(BaseModel):
    type: str
    data: dict

def get_ingest_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Dependency to validate and return the user key from the X-API-Key header."""
    if not key_manager.is_valid_user_key(x_api_key):
        raise HTTPException(status_code=403, detail="Invalid X-API-Key.")
    return x_api_key

@app.post("/api/ingest", tags=["Incoming Data"])
async def post_ingest(payload: IngestData, user_key: str = Depends(get_ingest_key)):
    """
    A unified endpoint to receive any type of log data.
    The user key is passed via the X-API-Key header for better security.
    """
    await ws_manager.broadcast_to_user(user_key, {"type": payload.type, "data": payload.data})
    return {"status": "received"}

@app.post("/api/status", tags=["Incoming Data"])
async def post_status(request: Request, user_key: str = Depends(get_ingest_key)):
    """Endpoint to receive status updates, broadcast to WebSocket and forward to MQTT."""
    try:
        data = await request.json()
        # Unified message format
        message = {"type": "status", "data": data}

        # Broadcast to WebSocket
        await ws_manager.broadcast_to_user(user_key, message)

        # Forward to MQTT
        if mqtt_client := mqtt_manager.get_client(user_key):
            mqtt_client.publish(message)

        return {"status": "received"}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

@app.post("/api/arrival", tags=["Incoming Data"])
async def post_arrival(request: Request, user_key: str = Depends(get_ingest_key)):
    """Endpoint to receive arrival data, broadcast to WebSocket and forward to MQTT."""
    try:
        data = await request.json()
        # Unified message format
        message = {"type": "arrival", "data": data}

        # Broadcast to WebSocket
        await ws_manager.broadcast_to_user(user_key, message)

        # Forward to MQTT
        if mqtt_client := mqtt_manager.get_client(user_key):
            mqtt_client.publish(message)

        return {"status": "received"}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

@app.post("/api/exception", tags=["Incoming Data"])
async def post_exception(request: Request, user_key: str = Depends(get_ingest_key)):
    """Endpoint to receive exception data, broadcast to WebSocket and forward to MQTT."""
    try:
        data = await request.json()
        # Unified message format
        message = {"type": "exception", "data": data}

        # Broadcast to WebSocket
        await ws_manager.broadcast_to_user(user_key, message)

        # Forward to MQTT
        if mqtt_client := mqtt_manager.get_client(user_key):
            mqtt_client.publish(message)

        return {"status": "received"}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

@app.post("/api/control", tags=["Incoming Data"])
async def post_control(request: Request, user_key: str = Depends(get_ingest_key)):
    """Endpoint to receive control data, broadcast to WebSocket and forward to MQTT."""
    try:
        data = await request.json()
        # Unified message format
        message = {"type": "control", "data": data}

        # Broadcast to WebSocket
        await ws_manager.broadcast_to_user(user_key, message)

        # Forward to MQTT
        if mqtt_client := mqtt_manager.get_client(user_key):
            mqtt_client.publish(message)

        return {"status": "received"}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

# === Map Download APIs ===
@app.get("/field-map", tags=["Maps"])
def get_map_file(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token_hash = get_token_hash(authorization)
    json_file_path = os.path.join(OUTPUT_DIR, f"field_map_r_locations_{token_hash}.json")

    if not os.path.exists(json_file_path):
        return JSONResponse(
            status_code=202,  # Use 202 Accepted to indicate the request is being processed
            content={
                "status": "processing",
                "message": "Map data is being generated. Please try again in a few moments."
            }
        )

    return FileResponse(json_file_path, media_type="application/json", filename=f"field_map_r_locations_{token_hash}.json")

def mount_user_maps_folder(token_hash: str):
    """Dynamically mount the user's map folder if it exists and hasn't been mounted."""
    folder_name = f"{token_hash}_maps"
    mount_path = f"/{folder_name}"

    if mount_path in mounted_folders:
        return

    # OUTPUT_DIR is now an absolute path
    folder_path = os.path.join(OUTPUT_DIR, folder_name)

    if os.path.isdir(folder_path):
        app.mount(mount_path, StaticFiles(directory=folder_path), name=folder_name)
        mounted_folders.add(mount_path)
        print(f"✅ Dynamically mounted {mount_path} => {folder_path}")

@app.post("/trigger-refresh", tags=["Maps"])
def trigger_refresh(background_tasks: BackgroundTasks, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Nuwa RMS Authorization header.")

    token_hash = get_token_hash(authorization)

    def background_task(auth_token, t_hash):
        """Wrapper task to download maps and then mount the folder."""
        download_and_parse_maps(auth_token)
        mount_user_maps_folder(t_hash)

    background_tasks.add_task(background_task, authorization, token_hash)
    return {"status": "processing", "message": "Map update and mounting initiated."}

# === WebSocket Endpoint ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    if not key_manager.is_valid_user_key(token):
        await websocket.close(code=4001)
        return

    await ws_manager.connect(websocket, token)
    await mqtt_manager.ensure_connection(token)

    client_wrapper = mqtt_manager.get_client(token)
    initial_status = "Connected" if client_wrapper and client_wrapper.is_connected else "Not Configured or Disconnected"
    await ws_manager.broadcast_to_user(token, {"type": "system_status", "data": {"mqtt_status": initial_status}})

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, token)
        if not ws_manager.active_connections.get(token):
            await mqtt_manager.disconnect_user(token)

# === MQTT Configuration APIs ===
@app.get("/api/config-mqtt", tags=["MQTT"])
async def get_mqtt_config(user_key: str = Depends(verify_user_token)):
    config = await mqtt_manager.get_config(user_key)
    if config:
        return config
    return {}

@app.post("/api/config-mqtt", tags=["MQTT"])
async def set_mqtt_config(request: Request, user_key: str = Depends(verify_user_token)):
    config = await request.json()
    try:
        await mqtt_manager.set_config(user_key, config)
        client = mqtt_manager.get_client(user_key)
        if client and client.is_connected:
            status_message = f"Connected to {config.get('host')}"
            await ws_manager.broadcast_to_user(user_key, {"type": "system_status", "data": {"mqtt_status": status_message}})
            return {"status": "success", "message": "MQTT configuration saved and connected."}
        else:
            raise Exception("Failed to establish MQTT connection.")
    except Exception as e:
        error_message = f"Error: {str(e)}"
        await ws_manager.broadcast_to_user(user_key, {"type": "system_status", "data": {"mqtt_status": error_message}})
        raise HTTPException(status_code=400, detail=error_message)

# === i18n Language Loading ===
_i18n_cache = {}
def get_language_pack(lang: str = Query("en", alias="lang")):
    valid_langs = {"en", "zh_TW"}
    lang_code = lang if lang in valid_langs else "en"
    if lang_code in _i18n_cache:
        return {"lang_code": lang_code, "i18n": _i18n_cache[lang_code]}
    lang_file = f"locales/{lang_code}.json"
    try:
        with open(lang_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
            _i18n_cache[lang_code] = translations
            return {"lang_code": lang_code, "i18n": translations}
    except (FileNotFoundError, json.JSONDecodeError):
        with open("locales/en.json", "r", encoding="utf-8") as f:
            translations = json.load(f)
            _i18n_cache["en"] = translations
            return {"lang_code": "en", "i18n": translations}

# === Frontend Pages ===
@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def get_login_page(request: Request, lang_pack: dict = Depends(get_language_pack)):
    return templates.TemplateResponse("login.html", {"request": request, **lang_pack})

@app.get("/admin", response_class=HTMLResponse, tags=["Frontend"])
async def get_admin_page(request: Request, lang_pack: dict = Depends(get_language_pack)):
    return templates.TemplateResponse("admin.html", {"request": request, **lang_pack})

@app.get("/log", response_class=HTMLResponse, tags=["Frontend"])
async def get_log_page(request: Request, lang_pack: dict = Depends(get_language_pack)):
    return templates.TemplateResponse("log.html", {"request": request, **lang_pack})

@app.get("/settings", response_class=HTMLResponse, tags=["Frontend"])
async def get_settings_page(request: Request, lang_pack: dict = Depends(get_language_pack)):
    return templates.TemplateResponse("settings.html", {"request": request, **lang_pack})

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "OK"}
