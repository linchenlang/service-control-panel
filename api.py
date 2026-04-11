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

# ---------- API 路由 ----------
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
        lines = request.args.get("lines", 15, type=int)
        safe_sid = sid.replace("/", "_").replace("\\", "_")
        log_file = LOGS_DIR / f"{safe_sid}.log"

        if not log_file.exists():
            error_msg = f"日志文件不存在: {log_file}"
            logger.error(error_msg)
            return jsonify({"error": error_msg, "logs": ""}), 404

        # 智能检测编码并读取
        def read_with_encoding(file_path, line_limit):
            # 尝试多种编码顺序
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1', 'cp1252']
            # 首先尝试用 chardet 检测（如果可用）
            try:
                import chardet
                with open(file_path, 'rb') as f:
                    raw_data = f.read(1024 * 10)  # 读取前10KB用于检测
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
            # 所有编码都失败，降级为二进制读取并强制替换
            with open(file_path, 'rb') as f:
                all_lines = f.readlines()
                last_lines = all_lines[-line_limit:] if all_lines else []
                decoded = [line.decode('utf-8', errors='replace') for line in last_lines]
                return "".join(decoded), "编码无法识别，已强制替换"

        content, warning = read_with_encoding(log_file, lines)
        response = {"logs": content, "error": warning}
        return jsonify(response)
    except PermissionError as e:
        error_msg = f"权限不足，无法读取日志文件: {log_file if 'log_file' in locals() else sid}. 请检查文件权限。"
        logger.error(error_msg, exc_info=True)
        return jsonify({"error": error_msg, "logs": ""}), 500
    except Exception as e:
        error_msg = f"读取日志失败: {str(e)} (文件: {log_file if 'log_file' in locals() else sid})"
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
    _public_ip_cache = {"ip": None, "time": 0}
    now = time.time()
    if _public_ip_cache["ip"] and (now - _public_ip_cache["time"]) < 300:
        return jsonify({"ip": _public_ip_cache["ip"]})
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
    _public_ip_cache = {"ip": public_ip, "time": now}
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
    """通过 ipconfig 命令获取详细的 IP 地址信息（Windows专用），完全基于正则提取 IPv6"""
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

    # 正则匹配 IPv6 地址（标准冒号十六进制，可带百分号）
    ipv6_pattern = r'\b([a-fA-F0-9:]+(?::[a-fA-F0-9]+)*)(?:%[0-9]+)?\b'

    adapters = []
    current_adapter = None
    lines = output.splitlines()
    for line in lines:
        line = line.rstrip()
        # 匹配适配器名称行
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

        # 提取 IPv4
        if "IPv4 地址" in line or "IP Address" in line:
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
            if ip_match:
                ip = ip_match.group(1)
                if not ip.startswith('169.254.'):
                    current_adapter["ipv4"].append(ip)

        # 提取普通 IPv6（非临时、非本地链接）
        elif "IPv6 地址" in line and "临时" not in line and "本地链接" not in line:
            ip_match = re.search(ipv6_pattern, line)
            if ip_match:
                ip = ip_match.group(1)
                # 过滤掉 fe80:: 和 ::1，且长度至少5
                if ip and not ip.startswith('fe80') and ip != '::1' and len(ip) >= 5:
                    current_adapter["ipv6"].append(ip)

        # 提取临时 IPv6 地址
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

@api.route("/")
def index():
    return render_template("index.html")
