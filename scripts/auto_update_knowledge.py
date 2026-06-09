import os
import requests
import time
from pathlib import Path

API_URL = "http://localhost:8000/api/knowledge/ingest"
TARGET_DIR = Path("data/raw_tactics")

def main():
    if not TARGET_DIR.exists():
        TARGET_DIR.mkdir(parents=True)
        print(f"创建目录 {TARGET_DIR}，请放入 txt 格式的原始战术文件，然后重新运行本脚本。")
        return

    files = list(TARGET_DIR.glob("*.txt"))
    if not files:
        print(f"在 {TARGET_DIR} 目录下没有找到 txt 文件。")
        return

    for file_path in files:
        print(f"正在上传文件: {file_path.name} ...")
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            print(f"⚠️ 文件 {file_path.name} 为空，跳过。")
            continue

        payload = {
            "source_text": content,
            "source_name": f"auto_script_{file_path.name}"
        }

        try:
            resp = requests.post(API_URL, json=payload)
            if resp.status_code == 200:
                print(f"✅ 成功提交: {resp.json()}")
            else:
                print(f"❌ 提交失败: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"请求失败 (请确认 FastAPI 服务正在运行): {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    main()
