import json
from pathlib import Path

CONFIG_FILE = Path("config.json")
LOGS_DIR = Path("./logs")
PID_DIR = Path("./pids")
MAINTENANCE_FILE = Path("./maintenance.json")
OPERATION_LOG_FILE = Path("./operations.jsonl")

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
SERVICES = config["services"]
PANEL_HOST = config.get("panel_host", "0.0.0.0")
PANEL_PORT = config.get("panel_port", 8888)

# 确保目录存在
LOGS_DIR.mkdir(exist_ok=True)
PID_DIR.mkdir(exist_ok=True)

# 维护模式状态
if MAINTENANCE_FILE.exists():
    with open(MAINTENANCE_FILE, "r") as f:
        maintenance = json.load(f)
else:
    maintenance = {}