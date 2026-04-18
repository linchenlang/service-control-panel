import json
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

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

# 部署配置（默认值）
DEFAULT_DEPLOYMENT = {
    "environment": "intranet",
    "has_public_ip": False,
    "firewall_enabled": True,
    "https_enabled": False,
    "allow_external_access": False,
    "auto_ban_ip": False,
    "risk_check_interval": 10,
    "admin_email": "",
    "notes": "",
    "os_type": "",
    "production_mode": False,
    "strict_mode": False,
    "enable_auto_fix": False,
    "monitor_network_traffic": True,
    "configured": True,
    "setup_done": True
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

# ---------- AI 助手配置（支持多模型） ----------
def load_ai_models():
    """加载多模型配置，返回模型列表，每个模型包含 name, key, url, model"""
    models_json = os.getenv("AI_MODELS", "")
    if models_json:
        try:
            models = json.loads(models_json)
            if isinstance(models, list) and len(models) > 0:
                return models
        except json.JSONDecodeError:
            print("警告: AI_MODELS 格式错误，使用单模型配置")
    # 回退到单模型配置
    single_model = {
        "name": os.getenv("AI_MODEL", "glm-4-flash"),
        "key": os.getenv("AI_API_KEY", ""),
        "url": os.getenv("AI_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        "model": os.getenv("AI_MODEL", "glm-4-flash")
    }
    return [single_model] if single_model["key"] else []

AI_MODELS = load_ai_models()
# 默认选中第一个模型
DEFAULT_AI_MODEL = AI_MODELS[0]["name"] if AI_MODELS else None

# 单模型兼容（供其他代码引用）
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_URL = os.getenv("AI_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
AI_HISTORY_FILE = Path("./ai_chat_history.json")
AI_MAX_HISTORY = 40

if not AI_API_KEY and not AI_MODELS:
    print("警告: 未设置 AI_API_KEY 或 AI_MODELS 环境变量，AI 助手功能将不可用。请在项目根目录创建 .env 文件并填写。")
