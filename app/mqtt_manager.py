import asyncio
import json
import logging
from typing import Dict, Any, Callable

import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_FILE = "mqtt_configs.json"

class MqttClientWrapper:
    def __init__(self, user_key: str, config: Dict[str, Any], on_message_callback: Callable):
        self.user_key = user_key
        self.config = config
        self.client = mqtt.Client(client_id=f"pms-map-service-{user_key}")
        self.client.on_message = lambda client, userdata, msg: on_message_callback(self.user_key, msg)
        self.is_connected = False

    def connect(self):
        try:
            if self.config.get("username"):
                self.client.username_pw_set(self.config["username"], self.config.get("password"))

            self.client.connect(self.config["host"], self.config["port"], 60)
            if self.config.get("subscribe_topic"):
                self.client.subscribe(self.config["subscribe_topic"])
            self.client.loop_start()
            self.is_connected = True
            logger.info(f"MQTT client for user {self.user_key[:5]}... connected to {self.config['host']}.")
        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect MQTT client for user {self.user_key[:5]}...: {e}")
            raise

    def disconnect(self):
        if self.client and self.is_connected:
            self.client.loop_stop()
            self.client.disconnect()
            self.is_connected = False
            logger.info(f"MQTT client for user {self.user_key[:5]}... disconnected.")

    def publish(self, data: Dict[str, Any]):
        if not self.is_connected:
            return

        topic = self.config.get("topics_by_type", {}).get(data.get("type")) or self.config.get("publish_topic")
        if topic:
            self.client.publish(topic, json.dumps(data))


class ConnectionManager:
    def __init__(self, config_file: str, on_message_callback: Callable):
        self.config_file = config_file
        self.configs = self._load_configs()
        self.clients: Dict[str, MqttClientWrapper] = {}
        self.on_message_callback = on_message_callback
        self.lock = asyncio.Lock()

    def _load_configs(self) -> Dict[str, Any]:
        try:
            with open(self.config_file, "r") as f:
                content = f.read()
                if not content:
                    return {}
                return json.loads(content)
        except FileNotFoundError:
            return {}
        except IsADirectoryError:
            logger.error(f"The path {self.config_file} is a directory, not a file. Please remove it.")
            return {}
        except json.JSONDecodeError:
            logger.error(f"Could not decode JSON from {self.config_file}")
            return {}

    async def _save_configs(self):
        async with self.lock:
            try:
                with open(self.config_file, "w") as f:
                    json.dump(self.configs, f, indent=2)
            except IOError as e:
                logger.error(f"Failed to save MQTT configs to {self.config_file}: {e}")

    async def get_config(self, user_key: str) -> Dict[str, Any] | None:
        async with self.lock:
            return self.configs.get(user_key)

    async def set_config(self, user_key: str, config: Dict[str, Any]):
        async with self.lock:
            self.configs[user_key] = config
        await self._save_configs()

        await self.disconnect_user(user_key)
        await self.ensure_connection(user_key)

    async def ensure_connection(self, user_key: str):
        async with self.lock:
            if user_key in self.clients and self.clients[user_key].is_connected:
                return

            user_config = self.configs.get(user_key)
            if user_config:
                logger.info(f"Establishing MQTT connection for user {user_key[:5]}...")
                client_wrapper = MqttClientWrapper(user_key, user_config, self.on_message_callback)
                try:
                    client_wrapper.connect()
                    self.clients[user_key] = client_wrapper
                except Exception:
                    pass

    async def disconnect_user(self, user_key: str):
        async with self.lock:
            if user_key in self.clients:
                client_wrapper = self.clients.pop(user_key)
                client_wrapper.disconnect()

    def get_client(self, user_key: str) -> MqttClientWrapper | None:
        return self.clients.get(user_key)
