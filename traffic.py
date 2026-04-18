import os
import time
import re
import threading
from collections import deque
from pathlib import Path
from config import LOGS_DIR, SERVICES

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

def update_traffic_background():
    # 初始化每个服务的日志位置
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
        time.sleep(5)  # 原频率5秒
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

traffic_thread = threading.Thread(target=update_traffic_background, daemon=True)
traffic_thread.start()