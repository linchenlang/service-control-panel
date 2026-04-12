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

# 部署配置（默认值：内网环境，无公网服务，防火墙已开启等）
DEFAULT_DEPLOYMENT = {
    "environment": "intranet",          # "intranet" 或 "internet"
    "has_public_ip": True,              # 是否有公网IP
    "firewall_enabled": True,           # 防火墙是否开启（用户自评）
    "https_enabled": False,             # 是否启用HTTPS
    "allow_external_access": False,     # 是否允许外网访问服务
    "notes": ""                         # 备注
}

# 读取部署配置，若不存在则使用默认值并保存
deployment_config = config.get("deployment", DEFAULT_DEPLOYMENT.copy())
if "deployment" not in config:
    config["deployment"] = deployment_config
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

# 确保目录存在
LOGS_DIR.mkdir(exist_ok=True)
PID_DIR.mkdir(exist_ok=True)

# 维护模式状态
if MAINTENANCE_FILE.exists():
    with open(MAINTENANCE_FILE, "r") as f:
        maintenance = json.load(f)
else:
    maintenance = {}