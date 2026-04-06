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

## 图片展示

<img width="1919" height="905" alt="屏幕截图 2026-04-06 203003" src="https://github.com/user-attachments/assets/15c3f642-245c-452c-8c10-a3dcc4bbe029" />

<img width="1919" height="899" alt="屏幕截图 2026-04-06 203034" src="https://github.com/user-attachments/assets/90a51143-fe84-49eb-82fe-3cd92a1a67a7" />

<img width="1917" height="901" alt="屏幕截图 2026-04-06 203043" src="https://github.com/user-attachments/assets/f27d89bb-1933-4029-b84e-4719e6308de0" />

<img width="1919" height="901" alt="屏幕截图 2026-04-06 203052" src="https://github.com/user-attachments/assets/7b24d5af-d4c6-4c00-90df-331eba9ff92c" />

<img width="1916" height="900" alt="屏幕截图 2026-04-06 203101" src="https://github.com/user-attachments/assets/9453b067-94e8-4243-848c-65459dcffafc" />

<img width="1918" height="904" alt="屏幕截图 2026-04-06 203119" src="https://github.com/user-attachments/assets/45782ef1-49dc-4fdd-ae75-c94b9350e9db" />


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

配置文件 `config.json` 示例：

```json
{
  "panel_host": "0.0.0.0",
  "panel_port": 8888,
  "logs_dir": "./logs",
  "services": [
    {
      "id": "my_service",
      "name": "我的服务",
      "command": ["python3", "app.py"],
      "cwd": "/path/to/service",
      "port": 8000
    }
  ]
}
```

- `panel_host` / `panel_port`：面板监听地址和端口
- `logs_dir`：服务日志存放目录（自动创建）
- `services`：服务列表
  - `id`：唯一标识（用于 API）
  - `name`：显示名称
  - `command`：启动命令，字符串或数组形式
  - `cwd`：工作目录（绝对或相对面板根目录）
  - `port`：服务端口（仅用于展示，不影响实际）

## 运行

```bash
python app.py
```

启动后访问 `http://<服务器IP>:8888`。

面板默认不输出访问日志，仅当发生错误时才有控制台输出。

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

## 目录结构

```
service-control-panel/
├── app.py                 # 主入口
├── config.py              # 配置加载
├── models.py              # 数据模型（服务健康状态）
├── service_manager.py     # 服务启停、维护、PID 管理
├── monitor.py             # 系统资源监控（CPU/内存/磁盘/网络/传感器）
├── traffic.py             # HTTP 请求频率统计
├── api.py                 # 所有 API 路由（蓝图）
├── utils.py               # 工具函数（IP、进程、日志记录）
├── templates/
│   └── index.html         # 前端页面
├── static/
│   ├── style.css          # 样式
│   ├── script.js          # 前端逻辑
│   └── fonts/             # 字体文件（方正小标宋）
├── logs/                  # 服务日志（运行时创建）
├── pids/                  # PID 文件（运行时创建）
├── config.json            # 配置文件
├── maintenance.json       # 维护模式状态
├── operations.jsonl       # 操作记录
└── requirements.txt       # Python 依赖
```

## 注意事项

- 维护模式开启后，服务会被停止且无法通过面板启动，直到手动关闭维护。
- 跨设备停止检测依赖 `operations.jsonl` 中的记录和本机 IP 对比（5 分钟内有效）。
- 如果未安装 `psutil`，部分监控功能不可用（建议安装）。
- 在 Windows 系统上，IP 地址详情通过调用 `ipconfig /all` 解析，支持显示临时 IPv6 地址和普通 IPv6 地址。
- 网络接口和 IP 地址卡片默认每 5 分钟自动刷新一次，可通过界面上方的“刷新网络/IP”按钮手动更新。

## 开源协议

MIT License
