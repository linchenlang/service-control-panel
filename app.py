import logging
from logging.handlers import RotatingFileHandler
import sys
import webbrowser
import threading
import time
from flask import Flask, render_template, request, jsonify, redirect, url_for
from api import api
from config import PANEL_HOST, PANEL_PORT, config, CONFIG_FILE

# 配置面板自身日志
panel_log_handler = RotatingFileHandler('panel.log', maxBytes=1024*1024, backupCount=3, encoding='utf-8')
panel_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
panel_log_handler.setLevel(logging.DEBUG)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(panel_log_handler)

console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.ERROR)
root_logger.addHandler(console_handler)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.register_blueprint(api)

app.logger.addHandler(panel_log_handler)
app.logger.setLevel(logging.DEBUG)

# ---------- 配置向导相关 ----------
def is_first_run():
    """判断是否首次运行（未完成配置向导）"""
    deployment = config.get("deployment", {})
    return not deployment.get("setup_done", False)

def open_browser():
    """延迟打开浏览器"""
    def _open():
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{PANEL_PORT}/setup")
    threading.Thread(target=_open, daemon=True).start()

@app.route("/setup", methods=["GET", "POST"])
def setup_wizard():
    """配置向导页面"""
    if request.method == "POST":
        # 接收前端提交的配置
        data = request.json
        config["deployment"] = {
            "environment": data.get("environment", "intranet"),
            "has_public_ip": data.get("has_public_ip", False),
            "firewall_enabled": data.get("firewall_enabled", True),
            "https_enabled": data.get("https_enabled", False),
            "allow_external_access": data.get("allow_external_access", False),
            "auto_ban_ip": data.get("auto_ban_ip", True),       # 是否启用自动封禁IP
            "risk_check_interval": data.get("risk_check_interval", 60),  # 风险检测间隔（秒）
            "admin_email": data.get("admin_email", ""),         # 管理员邮箱（用于告警）
            "notes": data.get("notes", ""),
            "setup_done": True
        }
        import json
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return jsonify({"success": True, "message": "配置已保存，即将跳转到面板主页"})
    # GET 请求返回配置页面
    return render_template("setup.html")

# ---------- 主入口 ----------
if __name__ == "__main__":
    from service_manager import get_status
    from config import SERVICES
    for svc in SERVICES:
        get_status(svc["id"])
    
    # 首次运行检测
    if is_first_run():
        print("检测到首次运行或配置不完整，正在打开配置向导...")
        open_browser()
    
    app.run(host=PANEL_HOST, port=PANEL_PORT, debug=False, threaded=True)