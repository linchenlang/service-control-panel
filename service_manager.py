import os
import time
import subprocess
from pathlib import Path
from config import SERVICES, LOGS_DIR, maintenance
from utils import (
    is_process_running, read_pid, write_pid, remove_pid,
    kill_process_tree, log_operation, get_last_action
)
from models import service_health

def save_maintenance():
    from config import MAINTENANCE_FILE
    import json
    with open(MAINTENANCE_FILE, "w") as f:
        json.dump(maintenance, f)

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
            # Windows 下以共享读/写模式打开日志文件，允许其他进程读取
            import msvcrt
            # 确保目录存在
            log_file.parent.mkdir(parents=True, exist_ok=True)
            # 以追加模式打开，允许共享读
            log_fd = os.open(str(log_file), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o666)
            # 允许其他进程读写
            msvcrt.setmode(log_fd, os.O_BINARY)
            log_handle = os.fdopen(log_fd, 'a', encoding='utf-8')
            proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=log_handle,
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
    from config import SERVICES
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