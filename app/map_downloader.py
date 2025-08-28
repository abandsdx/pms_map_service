import os
import requests
import zipfile
import yaml
import json
import hashlib
import shutil

API_URL = "https://api.nuwarobotics.com/v1/rms/mission/fields"
DOWNLOAD_DIR = "maps"
OUTPUT_DIR = "outputs"

def get_token_hash(token: str) -> str:
    return hashlib.md5(token.encode()).hexdigest()[:8]

def download_and_parse_maps(token: str):
    headers = {"Authorization": token, "Content-Type": "application/json"}
    resp = requests.get(API_URL, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    fields = data.get("data", {}).get("payload", [])

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output = []

    for field in fields:
        field_id = field.get("fieldId", "")
        field_name = field.get("fieldName", "Unknown").replace(" ", "_")
        maps = field.get("map", [])

        field_entry = {"fieldId": field_id, "fieldName": field_name, "maps": []}
        field_folder = os.path.join(DOWNLOAD_DIR, field_name)
        os.makedirs(field_folder, exist_ok=True)

        for m in maps:
            map_name = m.get("name", "")
            map_uuid = m.get("mapUuid", "")
            floor = m.get("floor", "")
            url = m.get("url", "")
            if not url:
                continue

            zip_filename = f"{floor}_{map_name}_{map_uuid}.zip".replace("/", "_")
            zip_filepath = os.path.join(field_folder, zip_filename)

            if not os.path.exists(zip_filepath):
                r = requests.get(url, headers=headers)
                if r.status_code == 200:
                    with open(zip_filepath, "wb") as f:
                        f.write(r.content)
                else:
                    continue

            extract_folder = os.path.join(field_folder, f"{map_name}_{map_uuid}")
            if not os.path.exists(extract_folder):
                with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
                    zip_ref.extractall(extract_folder)

            # 搜尋必要檔案
            map_yaml_file = map_image_path = location_file = None
            for root, dirs, files in os.walk(extract_folder):
                if "map.yaml" in files:
                    map_yaml_file = os.path.join(root, "map.yaml")
                if "map.jpg" in files:
                    map_image_path = os.path.join(root, "map.jpg")
                if "location.yaml" in files:
                    location_file = os.path.join(root, "location.yaml")

            # 解析 origin
            map_origin = None
            if map_yaml_file:
                try:
                    with open(map_yaml_file, "r", encoding="utf-8") as f:
                        yaml_data = yaml.safe_load(f) or {}
                    origin = yaml_data.get("origin")
                    if isinstance(origin, list) and len(origin) >= 2:
                        map_origin = origin[:2]
                except Exception as e:
                    print(f"❗️讀取 map.yaml 出錯: {e}")

            # 解析 rLocations 與 coordinates
            r_keys = []
            coordinates = {}
            if location_file:
                try:
                    with open(location_file, "r", encoding="utf-8") as f:
                        loc_data = yaml.safe_load(f) or {}
                    loc_dict = loc_data.get("loc") if isinstance(loc_data.get("loc"), dict) else loc_data
                    for k, v in loc_dict.items():
                        if k.startswith("R") and isinstance(v, list) and len(v) >= 2:
                            r_keys.append(k)
                            coordinates[k] = v[:2]  # 只取前兩個數值
                except Exception:
                    pass

            # 複製 map.jpg
            token_hash = get_token_hash(token)
            map_output_dir = os.path.join(OUTPUT_DIR, f"{token_hash}_maps")
            os.makedirs(map_output_dir, exist_ok=True)

            saved_map_image = None
            if map_image_path and os.path.exists(map_image_path):
                dst_image_path = os.path.join(
                    map_output_dir,
                    f"{field_name}_{floor}_{map_name}_{map_uuid}.jpg".replace("/", "_")
                )
                shutil.copyfile(map_image_path, dst_image_path)
                saved_map_image = dst_image_path

            # 加入 map 資訊
            field_entry["maps"].append({
                "mapName": map_name,
                "mapUuid": map_uuid,
                "floor": floor,
                "rLocations": r_keys,
                "coordinates": coordinates,   # ✅ 新增
                "mapImage": saved_map_image,
                "mapOrigin": map_origin
            })

        output.append(field_entry)

    # 儲存 JSON
    token_hash = get_token_hash(token)
    json_file_path = os.path.join(OUTPUT_DIR, f"field_map_r_locations_{token_hash}.json")
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 成功產出：{json_file_path}")


# ===== 測試執行 =====
if __name__ == "__main__":
    token = "your_token_here"
    download_and_parse_maps(token)
