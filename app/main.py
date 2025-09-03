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
OUTPUT_DIR = "outputs"
mounted_folders = set()

# Setup Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# === WebSocket Connection Management ===
class WebSocketManager:
    def __init__(self):
        # Maps user_key to a set of active WebSocket connections
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
            if user_key in self.active_connections:
                self.active_connections[user_key].remove(websocket)
                if not self.active_connections[user_key]:
                    del self.active_connections[user_key]

    async def broadcast_to_user(self, user_key: str, data: dict):
        async with self.lock:
            if user_key in self.active_connections:
                for connection in self.active_connections[user_key]:
                    try:
                        await connection.send_json(data)
                    except WebSocketDisconnect:
                        # Handle disconnection during broadcast
                        self.active_connections[user_key].remove(connection)


ws_manager = WebSocketManager()

# === MQTT Message Handling & Broadcasting ===
async def on_mqtt_message_callback(user_key: str, msg):
    """Callback passed to MqttClientWrapper."""
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {"raw_payload": msg.payload.hex()}

    # Add metadata and broadcast to the specific user's WebSockets
    full_message = {"type": "mqtt", "data": data}
    # ... (add status text, timestamp, etc.)
    await ws_manager.broadcast_to_user(user_key, full_message)

# Instantiate the MQTT Connection Manager
mqtt_manager = ConnectionManager(config_file="mqtt_configs.json", on_message_callback=on_mqtt_message_callback)


# === Authentication Dependencies ===
def get_token_from_header(authorization: str = Header(..., alias="Authorization")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format. Must be 'Bearer <token>'.")
    return authorization[7:]

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
    """Checks a key and returns its role (admin or user)."""
    key = request.key
    if key_manager.is_valid_master_key(key):
        return {"role": "admin", "token": key}
    if key_manager.is_valid_user_key(key):
        return {"role": "user", "token": key}
    raise HTTPException(status_code=403, detail="Invalid API Key")

# === Admin APIs for Key Management ===
# ... (Admin APIs remain unchanged)
class RevokeKeyRequest(BaseModel):
    key_to_revoke: str

@app.get("/api/admin/keys", tags=["Admin"])
def list_user_keys(admin_auth: None = Depends(verify_master_key)):
    return {"user_keys": key_manager.get_all_user_keys()}

@app.post("/api/admin/generate-key", tags=["Admin"])
def generate_user_key(admin_auth: None = Depends(verify_master_key)):
    new_key = secrets.token_hex(16)
    if key_manager.add_key(new_key):
        return {"status": "success", "new_key": new_key}
    raise HTTPException(status_code=500, detail="Failed to add new key to key file.")

@app.post("/api/admin/revoke-key", tags=["Admin"])
def revoke_user_key(request: RevokeKeyRequest, admin_auth: None = Depends(verify_master_key)):
    if key_manager.revoke_key(request.key_to_revoke):
        return {"status": "success", "revoked_key": request.key_to_revoke}
    raise HTTPException(status_code=404, detail="Key not found or failed to revoke key.")


# === Map Download APIs ===
# ... (Map Download APIs remain unchanged)
@app.post("/trigger-refresh", tags=["Maps"])
def trigger_refresh(background_tasks: BackgroundTasks, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Nuwa RMS Authorization header.")
    token_hash = get_token_hash(authorization)
    background_tasks.add_task(download_and_parse_maps, authorization)
    # The mount logic should be reviewed, but is out of scope for this refactor.
    # background_tasks.add_task(mount_static_folder, f"{token_hash}_maps")
    return {"status": "processing", "message": "Map update and mounting initiated."}

@app.get("/field-map", tags=["Maps"])
def get_map_file(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Nuwa RMS Authorization header.")
    token_hash = get_token_hash(authorization)
    json_file_path = os.path.join(OUTPUT_DIR, f"field_map_r_locations_{token_hash}.json")
    if not os.path.exists(json_file_path):
        return JSONResponse(status_code=404, content={"error": "JSON file not found. Please trigger /trigger-refresh first."})
    return FileResponse(json_file_path, media_type="application/json")


# === WebSocket Endpoint (Refactored) ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket endpoint for real-time log streaming."""
    if not key_manager.is_valid_user_key(token):
        await websocket.close(code=4001)
        return

    await ws_manager.connect(websocket, token)
    await mqtt_manager.ensure_connection(token)

    # Send initial status
    client_wrapper = mqtt_manager.get_client(token)
    initial_status = "Connected" if client_wrapper and client_wrapper.is_connected else "Not Configured or Disconnected"
    await ws_manager.broadcast_to_user(token, {"type": "system_status", "data": {"mqtt_status": initial_status}})

    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, token)
        # Optional: Disconnect MQTT if no more WS connections for this user
        if not ws_manager.active_connections.get(token):
            await mqtt_manager.disconnect_user(token)

# === MQTT Configuration API (Refactored) ===
@app.get("/api/config-mqtt", tags=["MQTT"])
async def get_mqtt_config(user_key: str = Depends(verify_user_token)):
    """Gets the MQTT configuration for the authenticated user."""
    config = await mqtt_manager.get_config(user_key)
    if config:
        return config
    # Return a default structure if no config is set
    return {
        "host": "localhost", "port": 1883, "username": "", "password": "",
        "subscribe_topic": "robot/events", "publish_topic": "robot/events",
        "topics_by_type": {
            "arrival": "robot/arrival", "status": "robot/status",
            "exception": "robot/exception", "control": "robot/control"
        }
    }

@app.post("/api/config-mqtt", tags=["MQTT"])
async def set_mqtt_config(request: Request, user_key: str = Depends(verify_user_token)):
    config = await request.json()
    try:
        await mqtt_manager.set_config(user_key, config)
        # Check status after attempting to set/connect
        client = mqtt_manager.get_client(user_key)
        if client and client.is_connected:
            status_message = f"Connected to {config.get('host')}"
            await ws_manager.broadcast_to_user(user_key, {"type": "system_status", "data": {"mqtt_status": status_message}})
            return {"status": "success", "message": "MQTT configuration saved and connected."}
        else:
            raise Exception("Failed to establish MQTT connection with the new settings.")
    except Exception as e:
        error_message = f"Error: {str(e)}"
        await ws_manager.broadcast_to_user(user_key, {"type": "system_status", "data": {"mqtt_status": error_message}})
        raise HTTPException(status_code=400, detail=error_message)

# === Event Handling APIs (Refactored) ===
@app.post("/api/{event_type}", tags=["Events"])
async def handle_event(event_type: str, request: Request, user_key: str = Depends(verify_user_token)):
    if event_type not in ["arrival", "status", "exception", "control"]:
        raise HTTPException(status_code=404, detail="Invalid event type.")

    mqtt_client_wrapper = mqtt_manager.get_client(user_key)
    if not mqtt_client_wrapper or not mqtt_client_wrapper.is_connected:
        raise HTTPException(status_code=400, detail="MQTT is not configured or connected for this user.")

    payload = await request.json()
    data = {"type": event_type, "data": payload}
    mqtt_client_wrapper.publish(data)
    return {"status": "ok"}

# === i18n Language Loading ===
def get_language(lang: str = Query("en", alias="lang")):
    """Dependency to load the correct language file."""
    lang_file = f"locales/{lang}.json"
    if not os.path.exists(lang_file):
        lang = "en" # Default to English if language not found
        lang_file = "locales/en.json"
    with open(lang_file, "r") as f:
        return json.load(f)

# === Frontend & Docs ===
@app.get("/admin", response_class=HTMLResponse, tags=["Frontend"])
async def get_admin_page(request: Request, i18n: dict = Depends(get_language)):
    """Serves the admin page for key management."""
    return templates.TemplateResponse("admin.html", {"request": request, "i18n": i18n})

@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def get_login_page(request: Request, i18n: dict = Depends(get_language)):
    """Serves the main login page."""
    return templates.TemplateResponse("login.html", {"request": request, "i18n": i18n})

@app.get("/log", response_class=HTMLResponse, tags=["Frontend"])
async def get_log_page(request: Request, i18n: dict = Depends(get_language)):
    """Serves the main log viewer page."""
    return templates.TemplateResponse("log.html", {"request": request, "i18n": i18n})

@app.get("/settings", response_class=HTMLResponse, tags=["Frontend"])
async def get_settings_page(request: Request, i18n: dict = Depends(get_language)):
    """Serves the MQTT settings page."""
    # This part will need a user context to fetch the right config.
    # For now, we pass a default config structure.
    # The actual values will be fetched by JS after authentication.
    default_config = {
        "host": "localhost", "port": 1883, "username": "", "password": "",
        "subscribe_topic": "robot/events", "publish_topic": "robot/events",
        "topics_by_type": {
            "arrival": "robot/arrival", "status": "robot/status",
            "exception": "robot/exception", "control": "robot/control"
        }
    }
    return templates.TemplateResponse("settings.html", {"request": request, "i18n": i18n, "config": default_config})

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "OK", "message": "Server is running."}
