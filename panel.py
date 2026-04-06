import json
import os
import subprocess
import time
import socket
import re
import threading
import signal
from pathlib import Path
from collections import deque
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
SERVICES = config["services"]
LOGS_DIR = Path(config["logs_dir"])
LOGS_DIR.mkdir(exist_ok=True)
PID_DIR = Path("./pids")
PID_DIR.mkdir(exist_ok=True)
MAINTENANCE_FILE = Path("./maintenance.json")

if MAINTENANCE_FILE.exists():
    with open(MAINTENANCE_FILE, "r") as f:
        maintenance = json.load(f)
else:
    maintenance = {}

def save_maintenance():
    with open(MAINTENANCE_FILE, "w") as f:
        json.dump(maintenance, f)

OPERATION_LOG_FILE = Path("./operations.jsonl")
last_actions = {}

def log_operation(service_id, service_name, action, source_ip):
    record = {
        "timestamp": time.time(),
        "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
        "service_id": service_id,
        "service_name": service_name,
        "action": action,
        "source_ip": source_ip
    }
    with open(OPERATION_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    last_actions[service_id] = {
        "action": action,
        "source_ip": source_ip,
        "timestamp": time.time()
    }

def get_last_action(service_id):
    action = last_actions.get(service_id)
    if action and (time.time() - action["timestamp"] <= 300):
        return action
    return None

def get_operation_history(limit=100):
    if not OPERATION_LOG_FILE.exists():
        return []
    records = []
    with open(OPERATION_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except:
                pass
    records.reverse()
    return records[:limit]

def is_process_running(pid):
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except:
        if os.name == 'nt':
            output = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=2
            )
            return str(pid) in output.stdout
        else:
            try:
                os.kill(pid, 0)
                return True
            except:
                return False

def get_pid_file(service_id):
    return PID_DIR / f"{service_id}.pid"

def read_pid(service_id):
    pid_file = get_pid_file(service_id)
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except:
            return None
    return None

def write_pid(service_id, pid):
    get_pid_file(service_id).write_text(str(pid))

def remove_pid(service_id):
    pid_file = get_pid_file(service_id)
    try:
        if pid_file.exists():
            pid_file.unlink()
    except (PermissionError, OSError):
        pass

def kill_process_tree(pid):
    if os.name == 'nt':
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except:
            os.kill(pid, signal.SIGKILL)

service_health = {}

def start_service(service, source_ip="unknown"):
    sid = service["id"]
    name = service["name"]
    if maintenance.get(sid, False):
        service_health[sid] = "maintenance"
        return False, "服务处于维护模式，请先取消维护"
    if get_status(sid)["running"]:
        service_health[sid] = "running"
        return False, "服务已在运行中"

    cmd = service["command"]
    if isinstance(cmd, str):
        cmd = cmd.split()

    cwd = service.get("cwd", ".")
    env = os.environ.copy()
    env.update(service.get("env", {}))
    log_file = LOGS_DIR / f"{sid}.log"

    try:
        if os.name == 'nt':
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=log_file.open("a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=log_file.open("a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
        time.sleep(0.8)
        if not is_process_running(proc.pid):
            service_health[sid] = "start_failed"
            error_msg = ""
            if log_file.exists():
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    if lines:
                        error_msg = "".join(lines[-15:])
            return False, f"启动后立即崩溃，可能原因：\n{error_msg}"
        write_pid(sid, proc.pid)
        service_health[sid] = "running"
        log_operation(sid, name, "start", source_ip)
        return True, f"启动成功，PID: {proc.pid}"
    except Exception as e:
        service_health[sid] = "start_failed"
        error_detail = str(e)
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                if lines:
                    error_detail += "\n" + "".join(lines[-10:])
        return False, f"启动失败: {error_detail}"

def stop_service(service, source_ip="unknown", skip_maintenance=False):
    sid = service["id"]
    name = service["name"]
    pid = read_pid(sid)
    if not pid or not is_process_running(pid):
        remove_pid(sid)
        service_health[sid] = "stopped"
        return False, "服务未运行"
    kill_process_tree(pid)
    for _ in range(10):
        if not is_process_running(pid):
            break
        time.sleep(0.2)
    remove_pid(sid)
    service_health[sid] = "stopped"
    log_operation(sid, name, "stop", source_ip)
    return True, "已停止"

def restart_service(service, source_ip="unknown"):
    stop_service(service, source_ip)
    time.sleep(0.8)
    return start_service(service, source_ip)

def set_maintenance(service_id, enabled, source_ip="unknown"):
    svc = next((s for s in SERVICES if s["id"] == service_id), None)
    if not svc:
        return False, "服务不存在"
    if enabled:
        if get_status(service_id)["running"]:
            stop_service(svc, source_ip, skip_maintenance=True)
        maintenance[service_id] = True
        service_health[service_id] = "maintenance"
        save_maintenance()
        log_operation(service_id, svc["name"], "maintenance_on", source_ip)
        return True, "已进入维护模式，服务已停止"
    else:
        maintenance.pop(service_id, None)
        save_maintenance()
        if service_health.get(service_id) == "maintenance":
            service_health[service_id] = "stopped"
        log_operation(service_id, svc["name"], "maintenance_off", source_ip)
        return True, "已退出维护模式"

def get_status(service_id):
    pid = read_pid(service_id)
    running = False
    pid_display = None
    if pid and is_process_running(pid):
        running = True
        pid_display = pid
        if service_health.get(service_id) in ["crashed", "start_failed"]:
            service_health[service_id] = "running"
    else:
        if pid:
            remove_pid(service_id)
        if service_health.get(service_id) == "running":
            last_action = get_last_action(service_id)
            if not (last_action and last_action["action"] == "stop" and time.time() - last_action["timestamp"] < 10):
                service_health[service_id] = "crashed"
    return {"running": running, "pid": pid_display}

def get_service_health(service_id):
    if maintenance.get(service_id, False):
        return "maintenance"
    return service_health.get(service_id, "stopped")

# ---------- 流量统计（修复重启暴涨）----------
traffic_history = {}
traffic_lock = threading.Lock()
LAST_LOG_STATE = {}

def count_http_requests_in_log(log_path, last_state):
    if not log_path.exists():
        return 0, last_state if last_state else {"size": 0, "pos": 0}
    try:
        current_size = log_path.stat().st_size
        if last_state and last_state.get("size", 0) > current_size:
            last_state["pos"] = 0
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            if last_state and last_state.get("pos"):
                f.seek(last_state["pos"])
            new_lines = f.readlines()
            new_pos = f.tell()
        count = 0
        for line in new_lines:
            if re.search(r'\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b', line):
                count += 1
        new_state = {"size": current_size, "pos": new_pos}
        return count, new_state
    except:
        return 0, last_state if last_state else {"size": 0, "pos": 0}

def update_traffic_data():
    # 初始化每个服务的日志读取位置为文件末尾，避免重启后统计历史数据
    for svc in SERVICES:
        sid = svc["id"]
        log_path = LOGS_DIR / f"{sid}.log"
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)
                initial_pos = f.tell()
            LAST_LOG_STATE[sid] = {"size": log_path.stat().st_size, "pos": initial_pos}
        else:
            LAST_LOG_STATE[sid] = {"size": 0, "pos": 0}
    while True:
        time.sleep(5)
        with traffic_lock:
            for svc in SERVICES:
                sid = svc["id"]
                log_path = LOGS_DIR / f"{sid}.log"
                last_state = LAST_LOG_STATE.get(sid)
                req_count, new_state = count_http_requests_in_log(log_path, last_state)
                LAST_LOG_STATE[sid] = new_state
                if sid not in traffic_history:
                    traffic_history[sid] = deque(maxlen=20)
                traffic_history[sid].append(req_count)

traffic_thread = threading.Thread(target=update_traffic_data, daemon=True)
traffic_thread.start()

@app.route("/api/traffic/<sid>")
def api_traffic(sid):
    with traffic_lock:
        history = list(traffic_history.get(sid, []))
    return jsonify({"values": history})

# ---------- 系统资源 ----------
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("警告: psutil未安装，请运行: pip install psutil")

def get_cpu_info():
    if not PSUTIL_AVAILABLE:
        return {"error": "psutil not installed"}
    cpu_percent = psutil.cpu_percent(interval=0.2)
    cpu_freq = psutil.cpu_freq()
    cpu_model = "Unknown"
    try:
        if os.name == 'nt':
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            cpu_model = winreg.QueryValueEx(key, "ProcessorNameString")[0]
            winreg.CloseKey(key)
        else:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        cpu_model = line.split(":")[1].strip()
                        break
    except:
        pass
    return {
        "model": cpu_model,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "percent": cpu_percent,
        "freq_mhz": cpu_freq.current if cpu_freq else None
    }

def get_memory_info():
    if not PSUTIL_AVAILABLE:
        return {}
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024**3), 1),
        "used_gb": round(mem.used / (1024**3), 1),
        "percent": mem.percent
    }

def get_disk_info():
    if not PSUTIL_AVAILABLE:
        return []
    disks = []
    for part in psutil.disk_partitions():
        if part.fstype:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "mount": part.mountpoint,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "percent": usage.percent
                })
            except:
                pass
    return disks

def get_total_load():
    cpu = get_cpu_info().get("percent", 0)
    mem = get_memory_info().get("percent", 0)
    return round((cpu + mem) / 2, 1)

@app.route("/api/dashboard_stats")
def api_dashboard_stats():
    return jsonify({
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disks": get_disk_info(),
        "total_load": get_total_load()
    })

# ---------- 服务资源监控 ----------
_services_resources_cache = []
_resources_cache_lock = threading.Lock()

def update_services_resources_cache():
    global _services_resources_cache
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

if PSUTIL_AVAILABLE:
    resources_thread = threading.Thread(target=update_services_resources_cache, daemon=True)
    resources_thread.start()

@app.route("/api/services_resources")
def api_services_resources():
    if not PSUTIL_AVAILABLE:
        return jsonify([])
    with _resources_cache_lock:
        return jsonify(_services_resources_cache)

# ---------- 网络与磁盘IO ----------
net_io_history = deque(maxlen=20)
net_io_lock = threading.Lock()
_prev_net = None
_prev_time = None

def update_net_io():
    global _prev_net, _prev_time
    while True:
        time.sleep(2)
        if not PSUTIL_AVAILABLE:
            continue
        now = time.time()
        net = psutil.net_io_counters()
        current = (net.bytes_sent, net.bytes_recv)
        if _prev_net and _prev_time:
            dt = now - _prev_time
            if dt > 0:
                sent_speed = (current[0] - _prev_net[0]) / dt / 1024
                recv_speed = (current[1] - _prev_net[1]) / dt / 1024
                with net_io_lock:
                    net_io_history.append((sent_speed, recv_speed))
        _prev_net = current
        _prev_time = now

net_io_thread = threading.Thread(target=update_net_io, daemon=True)
net_io_thread.start()

@app.route("/api/net_io_history")
def api_net_io_history():
    with net_io_lock:
        history = list(net_io_history)
    return jsonify({"history": history})

disk_io_history = {}
disk_io_lock = threading.Lock()

def update_disk_io():
    global disk_io_history
    last_io = {}
    while True:
        time.sleep(2)
        if not PSUTIL_AVAILABLE:
            continue
        current_io = psutil.disk_io_counters(perdisk=True)
        for disk, counters in current_io.items():
            if disk not in last_io:
                last_io[disk] = (counters.read_bytes, counters.write_bytes)
                continue
            prev_read, prev_write = last_io[disk]
            read_rate = (counters.read_bytes - prev_read) / 2 / 1024
            write_rate = (counters.write_bytes - prev_write) / 2 / 1024
            last_io[disk] = (counters.read_bytes, counters.write_bytes)
            with disk_io_lock:
                if disk not in disk_io_history:
                    disk_io_history[disk] = deque(maxlen=20)
                disk_io_history[disk].append((read_rate, write_rate))
        for disk in list(disk_io_history.keys()):
            if disk not in current_io:
                del disk_io_history[disk]

disk_io_thread = threading.Thread(target=update_disk_io, daemon=True)
disk_io_thread.start()

@app.route("/api/disk_io")
def api_disk_io():
    with disk_io_lock:
        data = {disk: list(history) for disk, history in disk_io_history.items()}
    return jsonify(data)

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
                except Exception as e:
                    print(f"Error processing service {svc['id']}: {e}")
                    continue
            with _services_cache_lock:
                _services_cache = statuses
        except Exception as e:
            print(f"Cache update thread error: {e}")
        time.sleep(1)

cache_thread = threading.Thread(target=update_services_cache, daemon=True)
cache_thread.start()

@app.route("/api/services", methods=["GET"])
def api_list_services():
    with _services_cache_lock:
        return jsonify(_services_cache)

# ---------- 服务配置管理 ----------
@app.route("/api/service_configs", methods=["GET"])
def api_get_service_configs():
    return jsonify(SERVICES)

@app.route("/api/service_configs", methods=["POST"])
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
    save_service_configs()
    reload_services()
    return jsonify({"success": True, "message": "服务添加成功"})

@app.route("/api/service_configs/<sid>", methods=["PUT"])
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
    save_service_configs()
    reload_services()
    return jsonify({"success": True, "message": "服务更新成功"})

@app.route("/api/service_configs/<sid>", methods=["DELETE"])
def api_delete_service(sid):
    idx = next((i for i, s in enumerate(SERVICES) if s["id"] == sid), None)
    if idx is None:
        return jsonify({"success": False, "message": "服务不存在"}), 404
    svc = SERVICES[idx]
    if get_status(sid)["running"]:
        stop_service(svc, "system")
    maintenance.pop(sid, None)
    save_maintenance()
    SERVICES.pop(idx)
    save_service_configs()
    reload_services()
    return jsonify({"success": True, "message": "服务已删除"})

def save_service_configs():
    config["services"] = SERVICES
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def reload_services():
    global SERVICES, traffic_history, LAST_LOG_STATE
    new_config = load_config()
    SERVICES = new_config["services"]
    with traffic_lock:
        existing_ids = {s["id"] for s in SERVICES}
        for sid in list(traffic_history.keys()):
            if sid not in existing_ids:
                del traffic_history[sid]
        for sid in list(LAST_LOG_STATE.keys()):
            if sid not in existing_ids:
                del LAST_LOG_STATE[sid]

# ---------- 传感器数据 ----------
def get_sensor_data():
    data = {
        "temperatures": None,
        "battery": None,
        "fans": None,
        "cpu_freq": None,
        "uptime": None,
        "process_count": None,
        "network_interfaces": None
    }
    if not PSUTIL_AVAILABLE:
        return data
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries and entries[0].current:
                    data["temperatures"] = {
                        "name": name,
                        "current": round(entries[0].current, 1),
                        "high": round(entries[0].high, 1) if entries[0].high else None,
                        "critical": round(entries[0].critical, 1) if entries[0].critical else None
                    }
                    break
    except:
        pass
    try:
        battery = psutil.sensors_battery()
        if battery:
            secsleft = battery.secsleft
            if secsleft == psutil.POWER_TIME_UNLIMITED:
                time_str = "无限（电源已接通）"
            elif secsleft == psutil.POWER_TIME_UNKNOWN or secsleft < 0:
                time_str = "未知"
            else:
                hours = secsleft // 3600
                minutes = (secsleft % 3600) // 60
                if hours > 24:
                    days = hours // 24
                    hours = hours % 24
                    time_str = f"{days}天 {hours}小时 {minutes}分钟"
                else:
                    time_str = f"{hours}小时 {minutes}分钟"
            data["battery"] = {
                "percent": battery.percent,
                "power_plugged": battery.power_plugged,
                "seconds_left": secsleft,
                "time_str": time_str
            }
    except:
        pass
    try:
        fans = psutil.sensors_fans()
        if fans:
            for name, entries in fans.items():
                if entries and entries[0].current:
                    data["fans"] = {
                        "name": name,
                        "rpm": entries[0].current
                    }
                    break
    except:
        pass
    try:
        cpu_freq = psutil.cpu_freq()
        if cpu_freq:
            data["cpu_freq"] = {
                "current": round(cpu_freq.current, 0),
                "max": round(cpu_freq.max, 0) if cpu_freq.max else None
            }
    except:
        pass
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        data["uptime"] = f"{days}天 {hours}小时 {minutes}分钟"
    except:
        pass
    try:
        data["process_count"] = len(psutil.pids())
    except:
        pass
    try:
        ifaces = []
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    ifaces.append({"name": name, "ip": addr.address})
                    break
        data["network_interfaces"] = ifaces[:3]
    except:
        pass
    return data

@app.route("/api/sensors")
def api_sensors():
    return jsonify(get_sensor_data())

@app.route("/api/services/<sid>/clear_log", methods=["POST"])
def api_clear_log(sid):
    log_file = LOGS_DIR / f"{sid}.log"
    try:
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")
            with traffic_lock:
                LAST_LOG_STATE[sid] = {"size": 0, "pos": 0}
                if sid in traffic_history:
                    traffic_history[sid] = deque(maxlen=20)
            return jsonify({"success": True, "message": "日志已清空"})
        else:
            return jsonify({"success": False, "message": "日志文件不存在"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/my_ip", methods=["GET"])
def api_my_ip():
    return jsonify({"ip": request.remote_addr or get_local_ip()})

@app.route("/api/operation_history", methods=["GET"])
def api_operation_history():
    limit = request.args.get("limit", 100, type=int)
    return jsonify(get_operation_history(limit))

@app.route("/api/services/<sid>/start", methods=["POST"])
def api_start(sid):
    svc = next((s for s in SERVICES if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "服务不存在"}), 404
    source_ip = request.remote_addr or "unknown"
    ok, msg = start_service(svc, source_ip)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/services/<sid>/stop", methods=["POST"])
def api_stop(sid):
    svc = next((s for s in SERVICES if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "服务不存在"}), 404
    source_ip = request.remote_addr or "unknown"
    ok, msg = stop_service(svc, source_ip)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/services/<sid>/restart", methods=["POST"])
def api_restart(sid):
    svc = next((s for s in SERVICES if s["id"] == sid), None)
    if not svc:
        return jsonify({"error": "服务不存在"}), 404
    source_ip = request.remote_addr or "unknown"
    ok, msg = restart_service(svc, source_ip)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/services/<sid>/maintenance", methods=["POST"])
def api_maintenance(sid):
    data = request.json
    enabled = data.get("enabled", False)
    source_ip = request.remote_addr or "unknown"
    ok, msg = set_maintenance(sid, enabled, source_ip)
    return jsonify({"success": ok, "message": msg})

@app.route("/api/services/<sid>/logs", methods=["GET"])
def api_logs(sid):
    lines = request.args.get("lines", 15, type=int)
    log_file = LOGS_DIR / f"{sid}.log"
    if not log_file.exists():
        return jsonify({"logs": ""})
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        all_lines = f.readlines()
        last_lines = all_lines[-lines:] if all_lines else []
        return jsonify({"logs": "".join(last_lines)})

@app.route("/api/start_all", methods=["POST"])
def api_start_all():
    source_ip = request.remote_addr or "unknown"
    results = []
    for svc in SERVICES:
        ok, msg = start_service(svc, source_ip)
        results.append({"name": svc["name"], "success": ok, "message": msg})
    return jsonify(results)

@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    source_ip = request.remote_addr or "unknown"
    results = []
    for svc in SERVICES:
        ok, msg = stop_service(svc, source_ip)
        results.append({"name": svc["name"], "success": ok, "message": msg})
    return jsonify(results)

@app.route("/api/settings", methods=["GET", "POST"])
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
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return jsonify({"success": True, "message": "配置已保存，请重启面板生效"})

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def clean_stale_pids():
    for svc in SERVICES:
        get_status(svc["id"])

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    clean_stale_pids()
    socketio.run(app, host=config.get("panel_host", "0.0.0.0"), port=config.get("panel_port", 8888), debug=False)
