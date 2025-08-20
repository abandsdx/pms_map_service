import os
import requests
import zipfile
import yaml
import json
import hashlib
import shutil  # ✅ 新增：用來複製圖片

API_URL = "https://api.nuwarobotics.com/v1/rms/mission/fields"
DOWNLOAD_DIR = "maps"
OUTPUT_DIR = "outputs"

def get_token_hash(token: str) -> str:
    return hashlib.md5(token.encode()).hexdigest()[:8]

def download_and_parse_maps(token: str):
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }

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

        field_entry = {
            "fieldId": field_id,
            "fieldName": field_name,
            "maps": []
        }

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

            location_file = None
            map_image_path = None  # ✅ 儲存 map.jpg 路徑

            for root, dirs, files in os.walk(extract_folder):
                if "location.yaml" in files:
                    location_file = os.path.join(root, "location.yaml")
                if "map.jpg" in files:
                    map_image_path = os.path.join(root, "map.jpg")  # ✅ 取得 map.jpg 完整路徑

            if not location_file:
                continue

            try:
                with open(location_file, "r", encoding="utf-8") as f:
                    loc_data = yaml.safe_load(f) or {}
            except Exception:
                continue

            if isinstance(loc_data.get("loc"), dict):
                loc_dict = loc_data["loc"]
            else:
                loc_dict = {k: v for k, v in loc_data.items() if isinstance(k, str) and isinstance(v, list) and k.startswith("R")}

            r_keys = [k for k in loc_dict if k.startswith("R")]

            # ✅ 複製 map.jpg 到 OUTPUT_DIR/token_hash_maps 目錄下
            token_hash = get_token_hash(token)
            map_output_dir = os.path.join(OUTPUT_DIR, f"{token_hash}_maps")
            os.makedirs(map_output_dir, exist_ok=True)

            saved_map_image = None
            if map_image_path and os.path.exists(map_image_path):
                dst_image_path = os.path.join(map_output_dir, f"{field_name}_{floor}_{map_name}_{map_uuid}.jpg".replace("/", "_"))
                shutil.copyfile(map_image_path, dst_image_path)
                saved_map_image = dst_image_path

            field_entry["maps"].append({
                "mapName": map_name,
                "mapUuid": map_uuid,
                "floor": floor,
                "rLocations": r_keys,
                "mapOrigin" : map_origin,
                "mapImage": saved_map_image  # ✅ 回傳圖像路徑
            })

        output.append(field_entry)

    # 儲存為專屬 token 對應檔案
    json_file_path = os.path.join(OUTPUT_DIR, f"field_map_r_locations_{token_hash}.json")
    with open(json_file_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 成功產出：{json_file_path}")
