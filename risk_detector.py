"""
风险检测模块 - 企业级多维度风险扫描
支持根据部署环境（内网/公网）动态调整检测项
使用后台线程异步更新缓存，启动时不阻塞，避免卡顿
"""

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

from config import SERVICES, LOGS_DIR, CONFIG_FILE

# 尝试导入可选依赖
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

# 阈值配置
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

# 加载部署配置
def get_deployment_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config.get('deployment', {})
    except:
        return {}

def should_skip_public_risk():
    dep = get_deployment_config()
    env = dep.get('environment', 'intranet')
    return env == 'intranet'

# ---------- 缓存机制 ----------
_risks_cache = None          # None 表示尚未完成首次扫描
_risks_cache_time = 0
_risks_cache_lock = Lock()
CACHE_TTL = 60  # 缓存有效期60秒

def get_risks_cached():
    """获取风险列表，如果尚未完成首次扫描则返回 None"""
    global _risks_cache
    with _risks_cache_lock:
        if _risks_cache is None:
            return None
        return _risks_cache

def _perform_risk_scan():
    risks = []
    deployment = get_deployment_config()
    env = deployment.get('environment', 'intranet')
    has_public_ip = deployment.get('has_public_ip', False)
    firewall_enabled = deployment.get('firewall_enabled', True)
    https_enabled = deployment.get('https_enabled', False)
    allow_external = deployment.get('allow_external_access', False)

    risks.extend(_check_service_config_risks())
    if PSUTIL_AVAILABLE:
        risks.extend(_check_system_resource_risks())
    risks.extend(_check_security_risks(env, has_public_ip, firewall_enabled, https_enabled, allow_external))
    risks.extend(_check_log_risks())
    risks.extend(_check_dependency_risks())
    risks.extend(_check_performance_risks())
    risks.extend(_check_certificate_risks())
    if PSUTIL_AVAILABLE:
        risks.extend(_check_process_risks())
    risks.extend(_check_network_risks())
    risks.extend(_check_panel_risks())

    # 去重
    unique = []
    seen = set()
    for r in risks:
        key = (r['type'], r['detail'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

def detect_risks():
    return get_risks_cached()

# ---------- 检测函数（完整实现） ----------
def _check_service_config_risks():
    risks = []
    seen_ids = set()
    ports = {}
    for svc in SERVICES:
        sid = svc.get('id')
        name = svc.get('name', sid)
        if sid in seen_ids:
            risks.append({
                'type': '服务ID重复',
                'severity': 'high',
                'detail': f'服务ID "{sid}" 重复出现，可能导致操作混乱。',
                'solution': '修改重复的服务ID，确保每个服务ID唯一。'
            })
        else:
            seen_ids.add(sid)
        port = svc.get('port')
        if port:
            if port in ports:
                risks.append({
                    'type': '端口冲突',
                    'severity': 'high',
                    'detail': f'服务 "{name}" 与 "{ports[port]}" 使用了相同端口 {port}。',
                    'solution': '修改其中一个服务的端口号。'
                })
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
                    risks.append({
                        'type': '命令不可执行',
                        'severity': 'high',
                        'detail': f'服务 "{name}" 的启动命令 "{exe_path}" 在PATH中未找到。',
                        'solution': '安装对应程序或使用绝对路径。'
                    })
                elif os.path.isabs(exe_path) and not os.path.exists(exe_path):
                    risks.append({
                        'type': '命令不可执行',
                        'severity': 'high',
                        'detail': f'服务 "{name}" 的启动命令 "{exe_path}" 文件不存在。',
                        'solution': '检查路径是否正确。'
                    })
        cwd = svc.get('cwd', '.')
        if not os.path.isdir(cwd):
            risks.append({
                'type': '工作目录无效',
                'severity': 'high',
                'detail': f'服务 "{name}" 的工作目录 "{cwd}" 不存在。',
                'solution': '创建目录或修改cwd配置。'
            })
        env_vars = svc.get('env', {})
        for key, value in env_vars.items():
            if isinstance(value, str) and value.startswith('$'):
                env_var = value[1:]
                if env_var not in os.environ:
                    risks.append({
                        'type': '环境变量缺失',
                        'severity': 'medium',
                        'detail': f'服务 "{name}" 引用的环境变量 {env_var} 未设置。',
                        'solution': f'设置环境变量 {env_var}。'
                    })
    return risks

def _check_system_resource_risks():
    risks = []
    if not PSUTIL_AVAILABLE:
        return risks
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            if usage.percent > THRESHOLDS['disk_usage_percent']:
                risks.append({
                    'type': '磁盘空间不足',
                    'severity': 'high',
                    'detail': f'磁盘 {part.mountpoint} 使用率 {usage.percent}%，剩余 {usage.free // (1024**3)} GB。',
                    'solution': '清理磁盘或扩容。'
                })
        except:
            pass
    mem = psutil.virtual_memory()
    if mem.percent > THRESHOLDS['memory_percent']:
        risks.append({
            'type': '内存使用过高',
            'severity': 'medium',
            'detail': f'内存使用率 {mem.percent}%，已用 {mem.used // (1024**2)} MB。',
            'solution': '检查内存泄漏或增加内存。'
        })
    cpu_percent = psutil.cpu_percent(interval=1)
    if cpu_percent > THRESHOLDS['cpu_percent']:
        risks.append({
            'type': 'CPU使用过高',
            'severity': 'medium',
            'detail': f'CPU使用率 {cpu_percent}%。',
            'solution': '检查高CPU进程。'
        })
    process_count = len(psutil.pids())
    if process_count > THRESHOLDS['process_count']:
        risks.append({
            'type': '进程数过多',
            'severity': 'low',
            'detail': f'进程数 {process_count}，超过阈值。',
            'solution': '清理无用进程。'
        })
    return risks

def _check_security_risks(env, has_public_ip, firewall_enabled, https_enabled, allow_external):
    risks = []
    if env == 'internet' and not firewall_enabled:
        risks.append({
            'type': '防火墙未开启',
            'severity': 'high',
            'detail': '您配置为公网环境但防火墙未开启，存在严重安全风险。',
            'solution': '启用防火墙或限制入站规则。'
        })
    if env == 'internet' and has_public_ip and not https_enabled:
        risks.append({
            'type': '公网服务未加密',
            'severity': 'high',
            'detail': '服务器具有公网IP且允许外部访问，但未启用HTTPS，通信可能被窃听。',
            'solution': '配置SSL证书并启用HTTPS。'
        })
    try:
        if CONFIG_FILE.exists():
            content = CONFIG_FILE.read_text()
            if 'secret!' in content and 'SECRET_KEY' in content:
                severity = 'low' if env == 'intranet' else 'medium'
                risks.append({
                    'type': '使用默认密钥',
                    'severity': severity,
                    'detail': '面板SECRET_KEY仍为默认值"secret!"。',
                    'solution': '修改 app.py 中的 SECRET_KEY 为随机强密码。'
                })
    except:
        pass
    if sys.version_info < (3, 8):
        risks.append({
            'type': 'Python版本过旧',
            'severity': 'medium',
            'detail': f'Python {sys.version} 低于3.8。',
            'solution': '升级Python。'
        })
    return risks

def _check_log_risks():
    risks = []
    LOGS_DIR.mkdir(exist_ok=True)
    for log_file in LOGS_DIR.glob('*.log'):
        try:
            size_mb = log_file.stat().st_size / (1024*1024)
            if size_mb > THRESHOLDS['log_file_size_mb']:
                risks.append({
                    'type': '日志文件过大',
                    'severity': 'low',
                    'detail': f'{log_file.name} 大小 {size_mb:.1f} MB。',
                    'solution': '清空日志或配置轮转。'
                })
        except:
            pass
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            if lines:
                recent = lines[-100:]
                error_count = sum(1 for line in recent if 'ERROR' in line or 'CRITICAL' in line or 'Exception' in line)
                if error_count > THRESHOLDS['log_error_rate_per_minute']:
                    risks.append({
                        'type': '日志错误频率过高',
                        'severity': 'medium',
                        'detail': f'{log_file.name} 中错误数较多（最近100行有{error_count}个）。',
                        'solution': '检查对应服务。'
                    })
        except:
            pass
    return risks

def _check_dependency_risks():
    risks = []
    required_packages = ['flask', 'psutil', 'requests']
    for pkg in required_packages:
        try:
            __import__(pkg)
        except ImportError:
            risks.append({
                'type': '缺少Python依赖',
                'severity': 'high',
                'detail': f'{pkg} 未安装。',
                'solution': f'pip install {pkg}'
            })
    for svc in SERVICES:
        cmd = svc.get('command', '')
        if isinstance(cmd, str):
            cmd_lower = cmd.lower()
        else:
            cmd_lower = ' '.join(cmd).lower()
        if 'node' in cmd_lower or 'npm' in cmd_lower:
            if not shutil.which('node'):
                risks.append({
                    'type': 'Node.js未安装',
                    'severity': 'high',
                    'detail': f'服务 "{svc["name"]}" 需要Node.js。',
                    'solution': '安装Node.js。'
                })
                break
    return risks

def _check_performance_risks():
    risks = []
    if not REQUESTS_AVAILABLE:
        return risks
    for svc in SERVICES:
        port = svc.get('port')
        if port:
            try:
                start = time.time()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(('127.0.0.1', port))
                elapsed = time.time() - start
                sock.close()
                if result == 0 and elapsed > 1.0:
                    risks.append({
                        'type': '服务响应缓慢',
                        'severity': 'medium',
                        'detail': f'服务 "{svc["name"]}" 端口 {port} 连接耗时 {elapsed:.2f}秒。',
                        'solution': '检查服务性能。'
                    })
            except:
                pass
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
                            risks.append({
                                'type': 'SSL证书已过期',
                                'severity': 'high',
                                'detail': f'{p} 已于 {expire_date} 过期。',
                                'solution': '更新证书。'
                            })
                        elif days_left < THRESHOLDS['cert_expire_days']:
                            risks.append({
                                'type': 'SSL证书即将过期',
                                'severity': 'medium',
                                'detail': f'{p} 将在 {days_left} 天后过期。',
                                'solution': '提前更新证书。'
                            })
            except:
                pass
    return risks

def _check_process_risks():
    risks = []
    if not PSUTIL_AVAILABLE:
        return risks
    zombie_count = 0
    for proc in psutil.process_iter(['pid', 'status']):
        try:
            if proc.info['status'] == 'zombie':
                zombie_count += 1
        except:
            pass
    if zombie_count > THRESHOLDS['zombie_processes']:
        risks.append({
            'type': '僵尸进程过多',
            'severity': 'medium',
            'detail': f'系统存在 {zombie_count} 个僵尸进程。',
            'solution': '重启父进程或系统。'
        })
    high_cpu_procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
        try:
            cpu = proc.cpu_percent(interval=0.5)
            if cpu > 80:
                high_cpu_procs.append(f"{proc.info['name']}({proc.info['pid']}) {cpu}%")
        except:
            pass
    if high_cpu_procs:
        risks.append({
            'type': '高CPU占用进程',
            'severity': 'medium',
            'detail': f'高CPU进程: {", ".join(high_cpu_procs[:3])}',
            'solution': '检查并优化这些进程。'
        })
    return risks

def _check_network_risks():
    risks = []
    try:
        if PSUTIL_AVAILABLE:
            open_ports = sum(1 for conn in psutil.net_connections(kind='inet') if conn.status == 'LISTEN')
            if open_ports > THRESHOLDS['open_ports_limit']:
                risks.append({
                    'type': '开放端口过多',
                    'severity': 'low',
                    'detail': f'开放了 {open_ports} 个监听端口。',
                    'solution': '关闭不必要的服务。'
                })
            established = sum(1 for conn in psutil.net_connections(kind='inet') if conn.status == 'ESTABLISHED')
            if established > THRESHOLDS['established_connections']:
                risks.append({
                    'type': '网络连接数异常',
                    'severity': 'high',
                    'detail': f'ESTABLISHED连接数 {established}，可能遭受攻击。',
                    'solution': '检查流量来源，启用防火墙限流。'
                })
    except:
        pass
    return risks

def _check_panel_risks():
    risks = []
    backup_exists = any(CONFIG_FILE.parent.glob(f"{CONFIG_FILE.name}.bak*"))
    if not backup_exists:
        risks.append({
            'type': '缺少配置备份',
            'severity': 'low',
            'detail': '未找到配置文件备份。',
            'solution': '定期备份 config.json。'
        })
    logs_size = sum(f.stat().st_size for f in LOGS_DIR.glob('*.log') if f.is_file())
    if logs_size > 1024*1024*1024:
        risks.append({
            'type': '日志目录过大',
            'severity': 'low',
            'detail': f'logs目录总大小 {logs_size // (1024**2)} MB，超过1GB。',
            'solution': '定期清理旧日志。'
        })
    return risks

# ---------- 后台更新线程（启动后立即执行一次扫描） ----------
def _background_updater():
    global _risks_cache, _risks_cache_time
    # 立即执行首次扫描
    try:
        print("正在执行首次风险扫描...")
        new_risks = _perform_risk_scan()
        with _risks_cache_lock:
            _risks_cache = new_risks
            _risks_cache_time = time.time()
        print(f"首次风险扫描完成，发现 {len(new_risks)} 个风险")
    except Exception as e:
        print(f"首次风险扫描失败: {e}")
        with _risks_cache_lock:
            _risks_cache = []   # 失败时设为空列表，避免一直 None
    # 然后定期更新
    while True:
        time.sleep(CACHE_TTL)
        try:
            new_risks = _perform_risk_scan()
            with _risks_cache_lock:
                _risks_cache = new_risks
                _risks_cache_time = time.time()
        except Exception as e:
            print(f"风险检测后台更新失败: {e}")

_background_thread = threading.Thread(target=_background_updater, daemon=True)
_background_thread.start()
print("风险检测模块已启动（后台异步更新，启动后立即扫描）")