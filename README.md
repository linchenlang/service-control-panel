# 服务控制面板

一个用于集中管理多个本地服务的 Web 面板，支持启停、维护模式、系统资源监控、HTTP 请求频率统计、跨设备操作记录，并提供实时曲线图表。

## 特性

- 多服务管理（启动 / 停止 / 重启 / 维护模式）
- 系统资源监控（CPU / 内存 / 磁盘 / 网络 / 温度 / 电池等）
- 基于日志的 HTTP 请求频率统计（每 5 秒采样）
- 跨设备操作记录，自动识别其他来源的停止操作并弹窗提醒
- 服务意外崩溃告警
- 动态服务配置（Web 界面添加 / 编辑 / 删除服务，热重载）
- IP 地址详细信息展示（Windows 下调用 `ipconfig /all` 解析，支持 IPv6 临时地址）
- 静默运行（控制台不输出请求日志，仅保留必要错误）

## 环境要求

- Python 3.8+
- 支持 Windows / Linux / macOS（部分功能在 Windows 上更完善）
- 依赖见 `requirements.txt`

## 安装

```bash
git clone https://github.com/linchenlang/service-control-panel.git
cd service-control-panel
pip install -r requirements.txt
```

## 配置

复制 `config.json.example` 为 `config.json` 并按需修改。示例内容：

```json
{
  "panel_host": "0.0.0.0",
  "panel_port": 8888,
  "services": [
    {
      "id": "my_service",
      "name": "我的服务",
      "command": ["python3", "app.py"],
      "cwd": "/path/to/service",
      "port": 8000
    }
  ],
  "deployment": {
    "environment": "intranet",
    "has_public_ip": false,
    "firewall_enabled": true,
    "https_enabled": false,
    "allow_external_access": false,
    "auto_ban_ip": false,
    "risk_check_interval": 60,
    "admin_email": "",
    "notes": "",
    "setup_done": false
  }
}
```

- `panel_host` / `panel_port`：面板监听地址和端口
- `services`：服务列表
  - `id`：唯一标识（用于 API）
  - `name`：显示名称
  - `command`：启动命令，字符串或数组形式
  - `cwd`：工作目录（绝对或相对面板根目录）
  - `port`：服务端口（仅用于展示，不影响实际）
- `deployment`：部署环境配置（影响风险检测策略）

## 运行

```bash
python app.py
```

启动后访问 `http://<服务器IP>:8888`。首次运行会弹出配置向导，完成后即可正常使用。

面板默认不输出访问日志，仅当发生错误时才有控制台输出。



## 相关图片展示

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 202005" src="https://github.com/user-attachments/assets/a2127acf-fdeb-4d59-adb3-1e19bed6feda" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201949" src="https://github.com/user-attachments/assets/e97eb246-db0c-4b0b-b0c5-660757745756" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201938" src="https://github.com/user-attachments/assets/54cff05c-9fd2-430e-a681-18e10fd5e7f8" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201925" src="https://github.com/user-attachments/assets/f2518247-2c5e-4d64-89b0-c34a98c45cbf" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201913" src="https://github.com/user-attachments/assets/c612389e-dccb-4053-8b14-c07b267f20c3" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201903" src="https://github.com/user-attachments/assets/65898fe8-02c7-4d88-972d-823e9ce559c0" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201850" src="https://github.com/user-attachments/assets/91f211ae-b885-4f95-9fe4-32e8c29e7a0e" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201843" src="https://github.com/user-attachments/assets/8612dc2e-4592-42fe-b21b-7c1de3579a53" />

<img width="1915" height="1079" alt="屏幕截图 2026-04-12 201835" src="https://github.com/user-attachments/assets/06b4ba4e-4c12-486d-be1d-8c02704e4108" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201824" src="https://github.com/user-attachments/assets/338ebb75-2676-4065-9442-c20eca54f29a" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201807" src="https://github.com/user-attachments/assets/7bd16e00-272b-434e-900b-74fbaf1331ee" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-12 201756" src="https://github.com/user-attachments/assets/c6926592-d8e2-428d-a0fb-d86583e9f061" />


## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/services` | 获取所有服务状态（含 PID、维护模式等） |
| POST | `/api/services/{id}/start` | 启动服务 |
| POST | `/api/services/{id}/stop` | 停止服务 |
| POST | `/api/services/{id}/restart` | 重启服务 |
| POST | `/api/services/{id}/maintenance` | 设置维护模式（`{"enabled": true/false}`） |
| GET | `/api/services/{id}/logs` | 获取服务日志（默认最后 15 行） |
| POST | `/api/services/{id}/clear_log` | 清空服务日志 |
| GET | `/api/dashboard_stats` | 获取系统资源（CPU、内存、磁盘、总负载） |
| GET | `/api/traffic/{id}` | 获取服务请求频率历史（每 5 秒采样，最多 20 个点） |
| GET | `/api/services_resources` | 获取每个服务当前的 CPU / 内存占用 |
| GET | `/api/net_io_history` | 获取网络上下行速率历史（KB/s） |
| GET | `/api/disk_io` | 获取磁盘读写速率历史 |
| GET | `/api/sensors` | 获取传感器数据（温度、电池、风扇、系统运行时间等） |
| GET | `/api/public_ip` | 获取公网 IPv4 地址（通过多个服务商） |
| GET | `/api/ip_detailed` | 获取详细 IP 地址列表（Windows 下解析 `ipconfig /all`） |
| GET | `/api/ipconfig_raw` | 返回 `ipconfig /all` 原始输出（Windows 专用） |
| GET | `/api/service_configs` | 获取当前服务配置列表 |
| POST | `/api/service_configs` | 添加新服务 |
| PUT | `/api/service_configs/{id}` | 修改服务配置 |
| DELETE | `/api/service_configs/{id}` | 删除服务配置 |
| GET | `/api/operation_history` | 获取操作记录（启动/停止/维护开关） |
| GET | `/api/risks` | 获取系统风险检测结果（支持内网/公网环境） |

## 目录结构

```
service-control-panel/
├── app.py                 # 主入口
├── config.py              # 配置加载
├── models.py              # 数据模型（服务健康状态）
├── service_manager.py     # 服务启停、维护、PID 管理
├── monitor.py             # 系统资源监控（CPU/内存/磁盘/网络/传感器）
├── traffic.py             # HTTP 请求频率统计
├── risk_detector.py       # 风险检测模块
├── api.py                 # 所有 API 路由（蓝图）
├── utils.py               # 工具函数（IP、进程、日志记录）
├── templates/
│   ├── index.html         # 主面板页面
│   └── setup.html         # 首次配置向导页面
├── static/
│   ├── style.css          # 样式
│   ├── script.js          # 前端逻辑
│   └── fonts/             # 字体文件（方正小标宋）
├── logs/                  # 服务日志（运行时创建）
├── pids/                  # PID 文件（运行时创建）
├── config.json.example    # 配置文件示例
├── maintenance.json       # 维护模式状态（运行时生成）
├── operations.jsonl       # 操作记录（运行时生成）
└── requirements.txt       # Python 依赖
```

## 注意事项

- 维护模式开启后，服务会被停止且无法通过面板启动，直到手动关闭维护。
- 跨设备停止检测依赖 `operations.jsonl` 中的记录和本机 IP 对比（5 分钟内有效）。
- 如果未安装 `psutil`，部分监控功能不可用（建议安装）。
- 在 Windows 系统上，IP 地址详情通过调用 `ipconfig /all` 解析，支持显示临时 IPv6 地址和普通 IPv6 地址。
- 风险检测模块启动后立即执行首次扫描，界面会显示“正在扫描”，约 1-2 秒后展示结果。

## 开源协议

MIT License
