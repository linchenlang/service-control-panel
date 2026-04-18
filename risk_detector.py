import os
import sys
import socket
import subprocess
import time
import re
import json
import shutil
import threading
from pathlib import Path
from datetime import datetime
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SERVICES, LOGS_DIR, CONFIG_FILE

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# 默认阈值（会被动态配置覆盖）
THRESHOLDS = {
    'disk_usage_percent': 85,
    'memory_percent': 85,
    'cpu_percent': 80,
    'log_file_size_mb': 100,
    'log_error_rate_per_minute': 10,
    'open_ports_limit': 100,
    'established_connections': 500,
    'process_count': 500,
    'zombie_processes': 5,
    'cert_expire_days': 30,
}

def get_deployment_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('deployment', {})
    except:
        return {}

# ---------- 缓存机制 ----------
_risks_cache = None
_risks_cache_time = 0
_risks_cache_lock = Lock()
_scanning = False
CACHE_TTL = 60

def get_risks_cached():
    global _risks_cache, _scanning
    with _risks_cache_lock:
        if _scanning or _risks_cache is None:
            return None
        return _risks_cache

def update_cache(new_risks):
    global _risks_cache, _risks_cache_time, _scanning
    with _risks_cache_lock:
        _risks_cache = new_risks
        _risks_cache_time = time.time()
        _scanning = False

def trigger_manual_scan():
    global _scanning
    with _risks_cache_lock:
        if _scanning:
            return False
        _scanning = True
    threading.Thread(target=_manual_scan_task, daemon=True).start()
    return True

def _manual_scan_task():
    try:
        new_risks = _perform_risk_scan()
        update_cache(new_risks)
        print(f"手动扫描完成，发现 {len(new_risks)} 个风险")
    except Exception as e:
        print(f"手动扫描失败: {e}")
        with _risks_cache_lock:
            _scanning = False

# ---------- 增量日志读取 ----------
_log_positions = {}  # {log_file_path: (size, pos, error_window)}
_log_lock = Lock()

def _read_incremental_log(log_path):
    """读取日志新增部分，返回新增行数和错误数"""
    with _log_lock:
        if not log_path.exists():
            return 0, 0
        st = log_path.stat()
        size = st.st_size
        last = _log_positions.get(str(log_path), (0, 0, []))
        last_size, last_pos, _ = last
        if size < last_size:
            last_pos = 0
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                if last_pos:
                    f.seek(last_pos)
                new_lines = f.readlines()
                new_pos = f.tell()
            error_count = 0
            for line in new_lines:
                if 'ERROR' in line or 'CRITICAL' in line or 'Exception' in line:
                    error_count += 1
            _log_positions[str(log_path)] = (size, new_pos, [])
            return len(new_lines), error_count
        except:
            return 0, 0

# ---------- 并发检测函数（受配置影响） ----------
def _check_service_config_risks():
    risks = []
    seen_ids = set()
    ports = {}
    for svc in SERVICES:
        sid = svc.get('id')
        name = svc.get('name', sid)
        if sid in seen_ids:
            risks.append({'type': '服务ID重复', 'severity': 'high', 'detail': f'服务ID "{sid}" 重复', 'solution': '修改重复ID。'})
        else:
            seen_ids.add(sid)
        port = svc.get('port')
        if port:
            if port in ports:
                risks.append({'type': '端口冲突', 'severity': 'high', 'detail': f'{name} 与 {ports[port]} 端口 {port} 冲突', 'solution': '修改端口。'})
            else:
                ports[port] = name
        cmd = svc.get('command')
        if cmd:
            if isinstance(cmd, str):
                cmd_parts = cmd.split()
            else:
                cmd_parts = cmd
            if cmd_parts:
                exe_path = cmd_parts[0]
                if not os.path.isabs(exe_path) and not shutil.which(exe_path):
                    risks.append({'type': '命令不可执行', 'severity': 'high', 'detail': f'{name} 命令 {exe_path} 未找到', 'solution': '安装或使用绝对路径。'})
                elif os.path.isabs(exe_path) and not os.path.exists(exe_path):
                    risks.append({'type': '命令不可执行', 'severity': 'high', 'detail': f'{name} 文件 {exe_path} 不存在', 'solution': '检查路径。'})
        cwd = svc.get('cwd', '.')
        if not os.path.isdir(cwd):
            risks.append({'type': '工作目录无效', 'severity': 'high', 'detail': f'{name} 目录 {cwd} 不存在', 'solution': '创建目录。'})
    return risks

def _check_system_resource_risks():
    if not PSUTIL_AVAILABLE:
        return []
    risks = []
    # 磁盘
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            if usage.percent > THRESHOLDS['disk_usage_percent']:
                risks.append({'type': '磁盘空间不足', 'severity': 'high', 'detail': f'{part.mountpoint} 使用率 {usage.percent}%', 'solution': '清理磁盘。'})
        except:
            pass
    # 内存
    mem = psutil.virtual_memory()
    if mem.percent > THRESHOLDS['memory_percent']:
        risks.append({'type': '内存使用过高', 'severity': 'medium', 'detail': f'内存使用率 {mem.percent}%', 'solution': '检查内存泄漏。'})
    # CPU（快速采样，不阻塞）
    cpu_percent = psutil.cpu_percent(interval=0.2)
    if cpu_percent > THRESHOLDS['cpu_percent']:
        risks.append({'type': 'CPU使用过高', 'severity': 'medium', 'detail': f'CPU使用率 {cpu_percent}%', 'solution': '检查高CPU进程。'})
    # 进程数
    process_count = len(psutil.pids())
    if process_count > THRESHOLDS['process_count']:
        risks.append({'type': '进程数过多', 'severity': 'low', 'detail': f'进程数 {process_count}', 'solution': '清理无用进程。'})
    return risks

def _check_security_risks():
    deployment = get_deployment_config()
    env = deployment.get('environment', 'intranet')
    has_public_ip = deployment.get('has_public_ip', False)
    firewall_enabled = deployment.get('firewall_enabled', True)
    https_enabled = deployment.get('https_enabled', False)
    risks = []
    if env == 'internet' and not firewall_enabled:
        risks.append({'type': '防火墙未开启', 'severity': 'high', 'detail': '公网环境防火墙未开启。', 'solution': '启用防火墙。'})
    if env == 'internet' and has_public_ip and not https_enabled:
        risks.append({'type': '公网服务未加密', 'severity': 'high', 'detail': '公网IP未启用HTTPS。', 'solution': '配置SSL。'})
    try:
        if CONFIG_FILE.exists() and 'secret!' in CONFIG_FILE.read_text():
            risks.append({'type': '使用默认密钥', 'severity': 'low' if env=='intranet' else 'medium', 'detail': 'SECRET_KEY为默认值。', 'solution': '修改为随机值。'})
    except:
        pass
    if sys.version_info < (3, 8):
        risks.append({'type': 'Python版本过旧', 'severity': 'medium', 'detail': f'Python {sys.version}', 'solution': '升级到3.8+。'})
    return risks

def _check_log_risks():
    risks = []
    LOGS_DIR.mkdir(exist_ok=True)
    for log_file in LOGS_DIR.glob('*.log'):
        # 文件大小
        try:
            size_mb = log_file.stat().st_size / (1024*1024)
            if size_mb > THRESHOLDS['log_file_size_mb']:
                risks.append({'type': '日志文件过大', 'severity': 'low', 'detail': f'{log_file.name} {size_mb:.1f} MB', 'solution': '清空或轮转。'})
        except:
            pass
        # 增量错误计数（简化：读取最后100行）
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()[-100:]
            error_count = sum(1 for line in lines if 'ERROR' in line or 'CRITICAL' in line or 'Exception' in line)
            if error_count > THRESHOLDS['log_error_rate_per_minute']:
                risks.append({'type': '日志错误频率过高', 'severity': 'medium', 'detail': f'{log_file.name} 错误数 {error_count}', 'solution': '检查服务。'})
        except:
            pass
    return risks

def _check_dependency_risks():
    risks = []
    for pkg in ['flask', 'psutil']:
        try:
            __import__(pkg)
        except ImportError:
            risks.append({'type': '缺少依赖', 'severity': 'high', 'detail': f'{pkg} 未安装。', 'solution': f'pip install {pkg}'})
    for svc in SERVICES:
        cmd = svc.get('command', '')
        if isinstance(cmd, str):
            cmd_lower = cmd.lower()
        else:
            cmd_lower = ' '.join(cmd).lower()
        if 'node' in cmd_lower and not shutil.which('node'):
            risks.append({'type': 'Node.js未安装', 'severity': 'high', 'detail': f'{svc["name"]} 需要Node.js', 'solution': '安装Node.js。'})
            break
    return risks

def _check_performance_risks():
    """并发检测所有服务的端口响应"""
    if not REQUESTS_AVAILABLE:
        return []
    risks = []
    def check_port(svc):
        port = svc.get('port')
        if not port:
            return None
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)  # 缩短超时
            sock.connect_ex(('127.0.0.1', port))
            elapsed = time.time() - start
            sock.close()
            if elapsed > 1.0:
                return {'type': '服务响应缓慢', 'severity': 'medium', 'detail': f'{svc["name"]} 端口{port} 耗时{elapsed:.2f}秒', 'solution': '优化服务性能。'}
        except:
            pass
        return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(check_port, svc): svc for svc in SERVICES}
        for future in as_completed(futures):
            result = future.result()
            if result:
                risks.append(result)
    return risks

def _check_certificate_risks():
    risks = []
    cert_paths = ['./cert.pem', './ssl/cert.pem', './certs/server.crt']
    for path in cert_paths:
        p = Path(path)
        if p.is_file():
            try:
                result = subprocess.run(['openssl', 'x509', '-in', str(p), '-noout', '-enddate'], capture_output=True, text=True, timeout=3)
                if result.returncode == 0:
                    match = re.search(r'notAfter=(.+)', result.stdout)
                    if match:
                        date_str = match.group(1).strip()
                        expire_date = datetime.strptime(date_str, '%b %d %H:%M:%S %Y %Z')
                        days_left = (expire_date - datetime.now()).days
                        if days_left < 0:
                            risks.append({'type': 'SSL证书已过期', 'severity': 'high', 'detail': f'{p} 已过期', 'solution': '更新证书。'})
                        elif days_left < THRESHOLDS['cert_expire_days']:
                            risks.append({'type': 'SSL证书即将过期', 'severity': 'medium', 'detail': f'{p} 将在 {days_left} 天后过期', 'solution': '提前更新。'})
            except:
                pass
    return risks

def _check_process_risks():
    if not PSUTIL_AVAILABLE:
        return []
    risks = []
    zombie_count = 0
    for proc in psutil.process_iter(['pid', 'status']):
        try:
            if proc.info['status'] == 'zombie':
                zombie_count += 1
        except:
            pass
    if zombie_count > THRESHOLDS['zombie_processes']:
        risks.append({'type': '僵尸进程过多', 'severity': 'medium', 'detail': f'僵尸进程 {zombie_count}', 'solution': '重启系统或父进程。'})
    high_cpu_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
        try:
            cpu = proc.cpu_percent(interval=0.1)
            if cpu > 80:
                high_cpu_procs.append(f"{proc.info['name']}({proc.info['pid']}) {cpu}%")
        except:
            pass
    if high_cpu_procs:
        risks.append({'type': '高CPU占用进程', 'severity': 'medium', 'detail': f'高CPU: {", ".join(high_cpu_procs[:3])}', 'solution': '优化或终止进程。'})
    return risks

def _check_network_risks():
    """网络风险检测（可通过配置关闭）"""
    if not PSUTIL_AVAILABLE:
        return []
    deployment = get_deployment_config()
    # 如果配置中关闭了网络流量监控，则跳过
    if not deployment.get('monitor_network_traffic', True):
        return []
    risks = []
    try:
        open_ports = sum(1 for conn in psutil.net_connections(kind='inet') if conn.status == 'LISTEN')
        if open_ports > THRESHOLDS['open_ports_limit']:
            risks.append({'type': '开放端口过多', 'severity': 'low', 'detail': f'开放 {open_ports} 个端口', 'solution': '关闭不必要服务。'})
        established = sum(1 for conn in psutil.net_connections(kind='inet') if conn.status == 'ESTABLISHED')
        if established > THRESHOLDS['established_connections']:
            risks.append({'type': '网络连接数异常', 'severity': 'high', 'detail': f'ESTABLISHED {established}', 'solution': '检查流量来源。'})
    except:
        pass
    return risks

def _check_panel_risks():
    risks = []
    backup_exists = any(CONFIG_FILE.parent.glob(f"{CONFIG_FILE.name}.bak*"))
    if not backup_exists:
        risks.append({'type': '缺少配置备份', 'severity': 'low', 'detail': '未找到备份。', 'solution': '定期备份 config.json。'})
    logs_size = sum(f.stat().st_size for f in LOGS_DIR.glob('*.log') if f.is_file())
    if logs_size > 1024*1024*1024:
        risks.append({'type': '日志目录过大', 'severity': 'low', 'detail': f'logs目录 {logs_size//(1024**2)} MB', 'solution': '清理旧日志。'})
    return risks

def _perform_risk_scan():
    """执行完整扫描（并发执行独立检测项），并应用配置影响"""
    global THRESHOLDS
    deployment = get_deployment_config()
    strict_mode = deployment.get('strict_mode', False)
    production_mode = deployment.get('production_mode', False)
    
    # 根据严格模式调整阈值
    if strict_mode:
        THRESHOLDS['disk_usage_percent'] = 70
        THRESHOLDS['memory_percent'] = 70
        THRESHOLDS['cpu_percent'] = 60
        THRESHOLDS['log_file_size_mb'] = 50
        THRESHOLDS['log_error_rate_per_minute'] = 5
        THRESHOLDS['open_ports_limit'] = 50
        THRESHOLDS['established_connections'] = 200
        THRESHOLDS['process_count'] = 300
        THRESHOLDS['zombie_processes'] = 2
    else:
        # 恢复默认
        THRESHOLDS['disk_usage_percent'] = 85
        THRESHOLDS['memory_percent'] = 85
        THRESHOLDS['cpu_percent'] = 80
        THRESHOLDS['log_file_size_mb'] = 100
        THRESHOLDS['log_error_rate_per_minute'] = 10
        THRESHOLDS['open_ports_limit'] = 100
        THRESHOLDS['established_connections'] = 500
        THRESHOLDS['process_count'] = 500
        THRESHOLDS['zombie_processes'] = 5
    
    risks = []
    # 使用线程池并发执行独立检测
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_check_service_config_risks): 'config',
            executor.submit(_check_system_resource_risks): 'system',
            executor.submit(_check_security_risks): 'security',
            executor.submit(_check_log_risks): 'log',
            executor.submit(_check_dependency_risks): 'dep',
            executor.submit(_check_performance_risks): 'perf',
            executor.submit(_check_certificate_risks): 'cert',
            executor.submit(_check_process_risks): 'proc',
            executor.submit(_check_network_risks): 'net',
            executor.submit(_check_panel_risks): 'panel',
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                risks.extend(result)
            except Exception as e:
                print(f"扫描项 {futures[future]} 失败: {e}")
    
    # 如果是生产环境，提升风险严重性
    if production_mode:
        for r in risks:
            if r['severity'] == 'medium':
                r['severity'] = 'high'
            elif r['severity'] == 'low':
                r['severity'] = 'medium'
    
    # 去重
    unique = []
    seen = set()
    for r in risks:
        key = (r['type'], r['detail'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

# ---------- 后台定期更新 ----------
def _background_updater():
    global _risks_cache, _risks_cache_time
    try:
        print("正在执行首次风险扫描...")
        new_risks = _perform_risk_scan()
        with _risks_cache_lock:
            _risks_cache = new_risks
            _risks_cache_time = time.time()
        print(f"首次扫描完成，发现 {len(new_risks)} 个风险")
    except Exception as e:
        print(f"首次扫描失败: {e}")
        with _risks_cache_lock:
            _risks_cache = []
    while True:
        time.sleep(CACHE_TTL)
        try:
            new_risks = _perform_risk_scan()
            with _risks_cache_lock:
                _risks_cache = new_risks
                _risks_cache_time = time.time()
        except Exception as e:
            print(f"定期扫描失败: {e}")

_background_thread = threading.Thread(target=_background_updater, daemon=True)
_background_thread.start()
print("风险检测模块已启动（高性能并发版，支持手动扫描，支持动态配置）")