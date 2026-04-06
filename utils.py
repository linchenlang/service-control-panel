import os
import time
import json
import subprocess
import socket
from pathlib import Path
from config import PID_DIR, OPERATION_LOG_FILE

_last_actions = {}  # 用于缓存最近操作（5分钟内）

def is_process_running(pid):
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
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
    _last_actions[service_id] = {
        "action": action,
        "source_ip": source_ip,
        "timestamp": time.time()
    }

def get_last_action(service_id):
    action = _last_actions.get(service_id)
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

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"