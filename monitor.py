import os
import time
import socket
import threading
from collections import deque
import psutil

PSUTIL_AVAILABLE = True  # 假设已安装

# 缓存数据
_cpu_info_cache = {}
_memory_info_cache = {}
_disk_info_cache = []
_total_load_cache = 0
_last_monitor_time = 0

# 网络IO历史
net_io_history = deque(maxlen=20)
net_io_lock = threading.Lock()
_prev_net = None
_prev_time = None

# 磁盘IO历史
disk_io_history = {}
disk_io_lock = threading.Lock()

def get_cpu_info():
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
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024**3), 1),
        "used_gb": round(mem.used / (1024**3), 1),
        "percent": mem.percent
    }

def get_disk_info():
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

def get_sensor_data():
    data = {
        "temperatures": None,
        "battery": None,
        "fans": None,
        "cpu_freq": None,
        "uptime": None,
        "process_count": None,
        "network_interfaces": []
    }
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
                if addr.family == socket.AF_INET:
                    if not addr.address.startswith("127."):
                        ifaces.append({"name": name, "ip": addr.address, "type": "IPv4"})
                elif addr.family == socket.AF_INET6:
                    if addr.address != "::1" and not addr.address.startswith("fe80"):
                        ifaces.append({"name": name, "ip": addr.address, "type": "IPv6"})
        data["network_interfaces"] = ifaces
    except:
        pass
    return data

# 后台更新网络IO历史
def update_net_io_background():
    global _prev_net, _prev_time
    while True:
        time.sleep(2)  # 保持原频率2秒
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

def update_disk_io_background():
    global disk_io_history
    last_io = {}
    while True:
        time.sleep(2)  # 保持原频率2秒
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

# 启动后台线程
net_thread = threading.Thread(target=update_net_io_background, daemon=True)
net_thread.start()
disk_thread = threading.Thread(target=update_disk_io_background, daemon=True)
disk_thread.start()