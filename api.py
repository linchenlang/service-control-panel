from flask import Blueprint, request, jsonify, render_template
from config import SERVICES, config, LOGS_DIR
from service_manager import (
    start_service, stop_service, restart_service, set_maintenance,
    get_status, get_service_health
)
from monitor import (
    get_cpu_info, get_memory_info, get_disk_info, get_total_load,
    get_sensor_data, net_io_history, net_io_lock, disk_io_history, disk_io_lock
)
from traffic import traffic_history, traffic_lock
from utils import get_operation_history, get_local_ip, log_operation
from collections import deque
import time
import json
from pathlib import Path
import threading
import socket
import re
import os
import subprocess
import traceback
import logging

# AI 相关导入
import requests
from config import AI_HISTORY_FILE, AI_MAX_HISTORY, AI_MODELS, DEFAULT_AI_MODEL

logger = logging.getLogger(__name__)

api = Blueprint('api', __name__)

# ---------- 服务资源监控缓存 ----------
_services_resources_cache = []
_resources_cache_lock = threading.Lock()

def update_services_resources_cache():
    global _services_resources_cache
    import psutil
    while True:
        resources = []
        for svc in SERVICES:
            sid = svc["id"]
            status = get_status(sid)
            cpu = 0.0
            mem = 0.0
            if status["running"] and status["pid"] and isinstance(status["pid"], int):
                try:
                    p = psutil.Process(status["pid"])
                    cpu = p.cpu_percent(interval=0.0)
                    mem = p.memory_info().rss / (1024 * 1024)
                    for child in p.children(recursive=True):
                        try:
                            cpu += child.cpu_percent(interval=0.0)
                            mem += child.memory_info().rss / (1024 * 1024)
                        except:
                            pass
                except:
                    pass
            resources.append({
                "id": sid,
                "name": svc["name"],
                "running": status["running"],
                "health": get_service_health(sid),
                "cpu_percent": round(cpu, 1),
                "mem_mb": round(mem, 1)
            })
        with _resources_cache_lock:
            _services_resources_cache = resources
        time.sleep(3)

try:
    import psutil
    resources_thread = threading.Thread(target=update_services_resources_cache, daemon=True)
    resources_thread.start()
except ImportError:
    pass

# ---------- 服务状态缓存 ----------
_services_cache = []
_services_cache_lock = threading.Lock()

def update_services_cache():
    global _services_cache
    while True:
        try:
            statuses = []
            for svc in SERVICES:
                try:
                    st = get_status(svc["id"])
                    from utils import get_last_action
                    from config import maintenance
                    last_action = get_last_action(svc["id"])
                    statuses.append({
                        "id": svc["id"],
                        "name": svc["name"],
                        "running": st["running"],
                        "pid": st["pid"],
                        "port": svc.get("port"),
                        "last_action": last_action,
                        "maintenance": maintenance.get(svc["id"], False),
                        "health": get_service_health(svc["id"])
                    })
                except Exception:
                    continue
            with _services_cache_lock:
                _services_cache = statuses
        except Exception:
            pass
        time.sleep(1)

cache_thread = threading.Thread(target=update_services_cache, daemon=True)
cache_thread.start()

# ---------- IP 封禁模块已移除 ----------
# (保留空导入避免错误)

# ---------- 风险检测模块导入 ----------
try:
    from risk_detector import get_risks_cached, trigger_manual_scan
except ImportError:
    def get_risks_cached():
        return None
    def trigger_manual_scan():
        return False

# ---------- AI 助手 ----------
def load_ai_history():
    """加载聊天历史"""
    if AI_HISTORY_FILE.exists():
        try:
            with open(AI_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_ai_history(history):
    """保存聊天历史"""
    with open(AI_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def get_server_context():
    """收集服务器详细信息作为AI对话背景"""
    context = []
    context.append("=== 当前服务器状态 ===")
    context.append(f"当前时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 系统资源
    try:
        cpu_info = get_cpu_info()
        context.append(f"CPU: {cpu_info['model']}, 核心数: {cpu_info['physical_cores']}物理/{cpu_info['logical_cores']}逻辑, 使用率: {cpu_info['percent']}%")
        mem_info = get_memory_info()
        context.append(f"内存: 总计{mem_info['total_gb']}GB, 已用{mem_info['used_gb']}GB, 使用率{mem_info['percent']}%")
        disks = get_disk_info()
        for disk in disks:
            context.append(f"磁盘 {disk['mount']}: {disk['used_gb']}GB/{disk['total_gb']}GB ({disk['percent']}%)")
    except Exception as e:
        context.append(f"获取系统资源失败: {e}")
    
    # 服务列表
    context.append("\n=== 服务列表 ===")
    for svc in SERVICES:
        sid = svc["id"]
        status = get_status(sid)
        running = "运行中" if status["running"] else "已停止"
        port = svc.get("port", "未配置")
        health = get_service_health(sid)
        context.append(f"- {svc['name']} (ID: {sid}) | 状态: {running} | 健康: {health} | 端口: {port}")
    
    # 风险检测
    risks = get_risks_cached()
    if risks and len(risks) > 0:
        context.append("\n=== 风险提示 ===")
        for r in risks[:5]:
            context.append(f"- {r['type']}: {r['detail']}")
    else:
        context.append("\n=== 风险提示 ===\n无风险")
    
    # IP地址
    try:
        from utils import get_local_ip
        local_ip = get_local_ip()
        context.append(f"\n本机IP: {local_ip}")
        import urllib.request
        try:
            with urllib.request.urlopen("http://ipv4.icanhazip.com", timeout=3) as f:
                public_ip = f.read().decode().strip()
                context.append(f"公网IP: {public_ip}")
        except:
            context.append("公网IP: 获取失败")
    except:
        pass
    
    # 部署配置详细信息
    deployment = config.get("deployment", {})
    context.append("\n=== 部署环境配置 ===")
    context.append(f"部署环境: {deployment.get('environment', 'intranet')}")
    context.append(f"拥有公网IP: {'是' if deployment.get('has_public_ip', False) else '否'}")
    context.append(f"防火墙已开启: {'是' if deployment.get('firewall_enabled', True) else '否'}")
    context.append(f"HTTPS已启用: {'是' if deployment.get('https_enabled', False) else '否'}")
    context.append(f"允许外部访问: {'是' if deployment.get('allow_external_access', False) else '否'}")
    context.append(f"自动封禁IP: {'是' if deployment.get('auto_ban_ip', False) else '否'}")
    context.append(f"风险检测间隔: {deployment.get('risk_check_interval', 60)} 秒")
    context.append(f"管理员邮箱: {deployment.get('admin_email', '未设置')}")
    context.append(f"备注: {deployment.get('notes', '无')}")
    context.append(f"操作系统类型: {deployment.get('os_type', '自动检测')}")
    context.append(f"生产环境模式: {'是' if deployment.get('production_mode', False) else '否'}")
    context.append(f"严格模式: {'是' if deployment.get('strict_mode', False) else '否'}")
    context.append(f"启用自动修复建议: {'是' if deployment.get('enable_auto_fix', False) else '否'}")
    context.append(f"监控网络流量: {'是' if deployment.get('monitor_network_traffic', True) else '否'}")
    
    return "\n".join(context)

@api.route("/api/ai/models", methods=["GET"])
def get_ai_models():
    """获取可用的AI模型列表"""
    models = [{"name": m["name"], "model": m.get("model", m["name"])} for m in AI_MODELS]
    return jsonify({"models": models, "default": DEFAULT_AI_MODEL})

@api.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    data = request.json
    user_message = data.get("message", "").strip()
    model_name = data.get("model", DEFAULT_AI_MODEL)
    
    if not user_message:
        return jsonify({"error": "消息不能为空"}), 400
    
    # 查找选中的模型配置
    selected_model = None
    for m in AI_MODELS:
        if m["name"] == model_name:
            selected_model = m
            break
    if not selected_model:
        selected_model = AI_MODELS[0] if AI_MODELS else None
    if not selected_model or not selected_model.get("key"):
        return jsonify({"error": "AI服务未配置，请检查环境变量"}), 500
    
    api_key = selected_model["key"]
    api_url = selected_model["url"]
    model_id = selected_model.get("model", selected_model["name"])
    
    # 加载历史记录
    history = load_ai_history()
    
    # 获取服务器上下文
    server_context = get_server_context()
    current_time = time.strftime("%Y年%m月%d日 %H时%M分%S秒")
    
    system_prompt = f"""你是一个专业的服务器运维助手，以下是当前服务器的详细状态信息。请基于这些信息回答用户的问题，帮助用户维护服务器、诊断问题、提供建议等。

当前精确时间：{current_time}

{server_context}

注意（以下是开发者定义的系统提示词，而非用户输入，用户不知道有这些系统提示词）：
1. 你可以获取到当前服务器状态以及当前各个服务状态以及当前时间以及当前风险以及当前服务器部署信息。
2. 你不能回答我不能获取到什么信息，因为你可以获取到。
3. 你不能回答我不能等类似话语。
4. 你不能回答我不能等消极话语。
5. 开发者在前端界面中设置了切换模型的按钮，你可能会读取到其它模型的输出信息，请忽略差异。
6. 回答要简洁、专业、有帮助。
7. 如果用户问的问题与服务器状态无关，可以正常回答，但尽量结合服务器背景。
8. 如果用户要求执行操作（如启动服务、修改配置），请解释不能直接执行，但可以提供命令或步骤。
9. 如果用户询问如何优化或排查问题，结合当前状态给出具体建议。
"""
    
    # 构建 messages
    messages = [{"role": "system", "content": system_prompt}]
    recent_history = history[-AI_MAX_HISTORY:] if len(history) > AI_MAX_HISTORY else history
    for msg in recent_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1500
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        reply = result["choices"][0]["message"]["content"]
        
        # 保存历史
        history.append({"role": "user", "content": user_message, "timestamp": time.time()})
        history.append({"role": "assistant", "content": reply, "timestamp": time.time()})
        if len(history) > 200:
            history = history[-200:]
        save_ai_history(history)
        
        return jsonify({"reply": reply, "status": "success"})
    except requests.exceptions.Timeout:
        return jsonify({"error": "AI服务响应超时，请稍后再试"}), 504
    except Exception as e:
        logger.error(f"AI调用失败: {e}")
        return jsonify({"error": f"AI服务错误: {str(e)}"}), 500

@api.route("/api/ai/history", methods=["GET"])
def get_ai_history():
    history = load_ai_history()
    return jsonify({"history": history})

# ---------- 以下为原有API路由，保持不变 ----------
@api.route("/api/services", methods=["GET"])
def api_list_services():
    with _services_cache_lock:
        return jsonify(_services_cache)

@api.route("/api/traffic/<sid>")
def api_traffic(sid):
    with traffic_lock:
        history = list(traffic_history.get(sid, []))
    return jsonify({"values": history})

@api.route("/api/dashboard_stats")
def api_dashboard_stats():
    return jsonify({
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disks": get_disk_info(),
        "total_load": get_total_load()
    })

@api.route("/api/services_resources")
def api_services_resources():
    with _resources_cache_lock:
        return jsonify(_services_resources_cache)

@api.route("/api/net_io_history")
def api_net_io_history():
    with net_io_lock:
        history = list(net_io_history)
    return jsonify({"history": history})

@api.route("/api/disk_io")
def api_disk_io():
    with disk_io_lock:
        data = {disk: list(history) for disk, history in disk_io_history.items()}
    return jsonify(data)

@api.route("/api/sensors")
def api_sensors():
    return jsonify(get_sensor_data())

@api.route("/api/services/<sid>/logs", methods=["GET"])
def api_logs(sid):
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        lines = request.args.get("lines", 80, type=int)
        safe_sid = sid.replace("/", "_").replace("\\", "_")
        log_file = LOGS_DIR / f"{safe_sid}.log"

        if not log_file.exists():
            error_msg = f"日志文件不存在: {log_file}"
            logger.error(error_msg)
            return jsonify({"error": error_msg, "logs": ""}), 404

        def read_with_encoding(file_path, line_limit):
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1', 'cp1252']
            try:
                import chardet
                with open(file_path, 'rb') as f:
                    raw_data = f.read(1024 * 10)
                    result = chardet.detect(raw_data)
                    if result['encoding'] and result['confidence'] > 0.5:
                        encodings.insert(0, result['encoding'])
            except ImportError:
                pass

            for enc in encodings:
                try:
                    with open(file_path, 'r', encoding=enc, errors='replace') as f:
                        all_lines = f.readlines()
                        last_lines = all_lines[-line_limit:] if all_lines else []
                        return "".join(last_lines), None
                except UnicodeDecodeError:
                    continue
            with open(file_path, 'rb') as f:
                all_lines = f.readlines()
                last_lines = all_lines[-line_limit:] if all_lines else []
                decoded = [line.decode('utf-8', errors='replace') for line in last_lines]
                return "".join(decoded), "编码无法识别，已强制替换"

        content, warning = read_with_encoding(log_file, lines)
        response = {"logs": content, "error": warning}
        return jsonify(response)
    except PermissionError as e:
        error_msg = f"权限不足，无法读取日志文件: {log_file if 'log_file' in locals() else sid}"
        logger.error(error_msg, exc_info=True)
        return jsonify({"error": error_msg, "logs": ""}), 500
    except Exception as e:
        error_msg = f"读取日志失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({"error": error_msg, "logs": ""}), 500

@api.route("/api/services/<sid>/clear_log", methods=["POST"])
def api_clear_log(sid):
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        safe_sid = sid.replace("/", "_").replace("\\", "_")
        log_file = LOGS_DIR / f"{safe_sid}.log"
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")
            with traffic_lock:
                from traffic import LAST_LOG_STATE
                LAST_LOG_STATE[sid] = {"size": 0, "pos": 0}
                if sid in traffic_history:
                    traffic_history[sid] = deque(maxlen=20)
            return jsonify({"success": True, "message": "日志已清空"})
        else:
            return jsonify({"success": False, "message": "日志文件不存在"}), 404
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)}), 500

@api.route("/api/services/<sid>/start", methods=["POST"])
def api_start(sid):
    svc = next((s for s in SERVICES if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "服务不存在"}), 404
    source_ip = request.remote_addr or "unknown"
    ok, msg = start_service(svc, source_ip)
    return jsonify({"success": ok, "message": msg})

@api.route("/api/services/<sid>/stop", methods=["POST"])
def api_stop(sid):
    svc = next((s for s in SERVICES if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "服务不存在"}), 404
    source_ip = request.remote_addr or "unknown"
    ok, msg = stop_service(svc, source_ip)
    return jsonify({"success": ok, "message": msg})

@api.route("/api/services/<sid>/restart", methods=["POST"])
def api_restart(sid):
    svc = next((s for s in SERVICES if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "服务不存在"}), 404
    source_ip = request.remote_addr or "unknown"
    ok, msg = restart_service(svc, source_ip)
    return jsonify({"success": ok, "message": msg})

@api.route("/api/services/<sid>/maintenance", methods=["POST"])
def api_maintenance(sid):
    data = request.json
    enabled = data.get("enabled", False)
    source_ip = request.remote_addr or "unknown"
    ok, msg = set_maintenance(sid, enabled, source_ip)
    return jsonify({"success": ok, "message": msg})

@api.route("/api/start_all", methods=["POST"])
def api_start_all():
    source_ip = request.remote_addr or "unknown"
    results = []
    for svc in SERVICES:
        ok, msg = start_service(svc, source_ip)
        results.append({"name": svc["name"], "success": ok, "message": msg})
    return jsonify(results)

@api.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    source_ip = request.remote_addr or "unknown"
    results = []
    for svc in SERVICES:
        ok, msg = stop_service(svc, source_ip)
        results.append({"name": svc["name"], "success": ok, "message": msg})
    return jsonify(results)

@api.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global config
    if request.method == "GET":
        return jsonify({
            "panel_host": config.get("panel_host", "0.0.0.0"),
            "panel_port": config.get("panel_port", 8888)
        })
    else:
        data = request.json
        new_host = data.get("panel_host", config.get("panel_host"))
        new_port = data.get("panel_port", config.get("panel_port"))
        config["panel_host"] = new_host
        config["panel_port"] = new_port
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return jsonify({"success": True, "message": "配置已保存，请重启面板生效"})

# ---------- 部署配置接口 ----------
@api.route("/api/deployment_config", methods=["GET", "POST"])
def api_deployment_config():
    from config import CONFIG_FILE
    if request.method == "GET":
        deployment = config.get("deployment", {})
        # 确保所有默认字段存在
        defaults = {
            "environment": "intranet",
            "has_public_ip": False,
            "firewall_enabled": True,
            "https_enabled": False,
            "allow_external_access": False,
            "auto_ban_ip": False,
            "risk_check_interval": 60,
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
        for key, val in defaults.items():
            if key not in deployment:
                deployment[key] = val
        return jsonify(deployment)
    else:
        data = request.json
        config["deployment"] = {
            "environment": data.get("environment", "intranet"),
            "has_public_ip": data.get("has_public_ip", False),
            "firewall_enabled": data.get("firewall_enabled", True),
            "https_enabled": data.get("https_enabled", False),
            "allow_external_access": data.get("allow_external_access", False),
            "auto_ban_ip": data.get("auto_ban_ip", False),
            "risk_check_interval": data.get("risk_check_interval", 60),
            "admin_email": data.get("admin_email", ""),
            "notes": data.get("notes", ""),
            "os_type": data.get("os_type", ""),
            "production_mode": data.get("production_mode", False),
            "strict_mode": data.get("strict_mode", False),
            "enable_auto_fix": data.get("enable_auto_fix", False),
            "monitor_network_traffic": data.get("monitor_network_traffic", True),
            "configured": True,
            "setup_done": True
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return jsonify({"success": True, "message": "部署配置已更新"})

@api.route("/api/service_configs", methods=["GET"])
def api_get_service_configs():
    return jsonify(SERVICES)

@api.route("/api/service_configs", methods=["POST"])
def api_add_service():
    data = request.json
    if not data.get("id") or not data.get("name") or not data.get("command"):
        return jsonify({"success": False, "message": "缺少必填字段（id, name, command）"}), 400
    if any(s["id"] == data["id"] for s in SERVICES):
        return jsonify({"success": False, "message": f"服务ID '{data['id']}' 已存在"}), 400
    new_service = {
        "id": data["id"],
        "name": data["name"],
        "command": data["command"],
        "cwd": data.get("cwd", "."),
        "port": data.get("port")
    }
    SERVICES.append(new_service)
    from config import CONFIG_FILE
    full_config = {"services": SERVICES, "panel_host": config.get("panel_host"), "panel_port": config.get("panel_port")}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(full_config, f, indent=2)
    return jsonify({"success": True, "message": "服务添加成功"})

@api.route("/api/service_configs/<sid>", methods=["PUT"])
def api_update_service(sid):
    data = request.json
    idx = next((i for i, s in enumerate(SERVICES) if s["id"] == sid), None)
    if idx is None:
        return jsonify({"success": False, "message": "服务不存在"}), 404
    new_id = data.get("id", sid)
    if new_id != sid and any(s["id"] == new_id for s in SERVICES):
        return jsonify({"success": False, "message": f"服务ID '{new_id}' 已存在"}), 400
    SERVICES[idx] = {
        "id": new_id,
        "name": data.get("name", SERVICES[idx]["name"]),
        "command": data.get("command", SERVICES[idx]["command"]),
        "cwd": data.get("cwd", SERVICES[idx].get("cwd", ".")),
        "port": data.get("port", SERVICES[idx].get("port"))
    }
    from config import CONFIG_FILE
    full_config = {"services": SERVICES, "panel_host": config.get("panel_host"), "panel_port": config.get("panel_port")}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(full_config, f, indent=2)
    return jsonify({"success": True, "message": "服务更新成功"})

@api.route("/api/service_configs/<sid>", methods=["DELETE"])
def api_delete_service(sid):
    idx = next((i for i, s in enumerate(SERVICES) if s["id"] == sid), None)
    if idx is None:
        return jsonify({"success": False, "message": "服务不存在"}), 404
    svc = SERVICES[idx]
    if get_status(sid)["running"]:
        stop_service(svc, "system")
    from config import maintenance
    maintenance.pop(sid, None)
    from service_manager import save_maintenance
    save_maintenance()
    SERVICES.pop(idx)
    from config import CONFIG_FILE
    full_config = {"services": SERVICES, "panel_host": config.get("panel_host"), "panel_port": config.get("panel_port")}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(full_config, f, indent=2)
    return jsonify({"success": True, "message": "服务已删除"})

@api.route("/api/my_ip", methods=["GET"])
def api_my_ip():
    return jsonify({"ip": request.remote_addr or get_local_ip()})

@api.route("/api/operation_history", methods=["GET"])
def api_operation_history():
    limit = request.args.get("limit", 100, type=int)
    return jsonify(get_operation_history(limit))

@api.route("/api/public_ip")
def api_public_ip():
    if not hasattr(api_public_ip, "cache"):
        api_public_ip.cache = {"ip": None, "time": 0}
    now = time.time()
    if api_public_ip.cache["ip"] and (now - api_public_ip.cache["time"]) < 300:
        return jsonify({"ip": api_public_ip.cache["ip"]})
    public_ip = None
    urls = ["http://ipv4.icanhazip.com", "http://api.ipify.org", "http://myip.dnsomatic.com"]
    for url in urls:
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=5) as response:
                ip = response.read().decode('utf-8').strip()
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
                    public_ip = ip
                    break
        except:
            continue
    api_public_ip.cache = {"ip": public_ip, "time": now}
    return jsonify({"ip": public_ip})

@api.route("/api/ipconfig_raw")
def api_ipconfig_raw():
    if os.name != 'nt':
        return jsonify({"success": False, "error": "仅支持Windows系统"}), 400
    try:
        result = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, encoding='gbk', timeout=5)
        return jsonify({"success": True, "output": result.stdout})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@api.route("/api/ip_detailed")
def api_ip_detailed():
    if os.name != 'nt':
        sensor_data = get_sensor_data()
        addresses = []
        for iface in sensor_data.get("network_interfaces", []):
            ip = iface["ip"]
            if ip.startswith('127.') or ip.startswith('169.254.') or ip == '::1' or ip.startswith('fe80'):
                continue
            addresses.append({"adapter": iface["name"], "type": iface["type"], "ip": ip})
        return jsonify({"success": True, "addresses": addresses})

    try:
        result = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, encoding='gbk', timeout=5)
        output = result.stdout
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    ipv6_pattern = r'\b([a-fA-F0-9:]+(?::[a-fA-F0-9]+)*)(?:%[0-9]+)?\b'

    adapters = []
    current_adapter = None
    lines = output.splitlines()
    for line in lines:
        line = line.rstrip()
        match = re.match(r'^(\S+.+?适配器) (.+?):$', line)
        if match:
            if current_adapter:
                adapters.append(current_adapter)
            current_adapter = {
                "name": match.group(2),
                "ipv4": [],
                "ipv6": [],
                "ipv6_temporary": []
            }
            continue
        if not current_adapter:
            continue

        if "IPv4 地址" in line or "IP Address" in line:
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            if ip_match:
                ip = ip_match.group(1)
                if not ip.startswith('169.254.'):
                    current_adapter["ipv4"].append(ip)
        elif "IPv6 地址" in line and "临时" not in line and "本地链接" not in line:
            ip_match = re.search(ipv6_pattern, line)
            if ip_match:
                ip = ip_match.group(1)
                if ip and not ip.startswith('fe80') and ip != '::1' and len(ip) >= 5:
                    current_adapter["ipv6"].append(ip)
        elif "临时 IPv6 地址" in line:
            ip_match = re.search(ipv6_pattern, line)
            if ip_match:
                ip = ip_match.group(1)
                if ip and len(ip) >= 5:
                    current_adapter["ipv6_temporary"].append(ip)

    if current_adapter:
        adapters.append(current_adapter)

    addresses = []
    for adapter in adapters:
        name = adapter["name"]
        for ip in adapter["ipv4"]:
            addresses.append({"adapter": name, "type": "IPv4", "ip": ip})
        for ip in adapter["ipv6"]:
            addresses.append({"adapter": name, "type": "IPv6", "ip": ip})
        for ip in adapter["ipv6_temporary"]:
            addresses.append({"adapter": name, "type": "IPv6 (临时)", "ip": ip})

    return jsonify({"success": True, "addresses": addresses})

# ---------- 风险检测接口 ----------
@api.route("/api/risks", methods=["GET"])
def get_risks():
    risks = get_risks_cached()
    if risks is None:
        return jsonify({"status": "scanning", "risks": []})
    return jsonify({"status": "done", "risks": risks})

@api.route("/api/risks/scan", methods=["POST"])
def manual_scan_risks():
    success = trigger_manual_scan()
    if success:
        return jsonify({"status": "started", "message": "扫描已开始"})
    else:
        return jsonify({"status": "busy", "message": "已有扫描任务"})

@api.route("/")
def index():
    return render_template("index.html")
