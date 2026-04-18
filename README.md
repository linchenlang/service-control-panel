# 服务控制面板

一个用于集中管理多个本地服务的 Web 面板，支持启停、维护模式、系统资源监控、HTTP 请求频率统计、跨设备操作记录、实时曲线图表，并内置 AI 运维助手。

## 特性

- 多服务管理（启动 / 停止 / 重启 / 维护模式）
- 系统资源监控（CPU / 内存 / 磁盘 / 网络 / 温度 / 电池等）
- 基于日志的 HTTP 请求频率统计（每 5 秒采样）
- 跨设备操作记录，自动识别其他来源的停止操作并弹窗提醒
- 服务意外崩溃告警
- 动态服务配置（Web 界面添加 / 编辑 / 删除服务，热重载）
- IP 地址详细信息展示（Windows 下调用 `ipconfig /all` 解析，支持 IPv6 临时地址）
- 静默运行（控制台不输出请求日志，仅保留必要错误）
- **AI 运维助手**：基于智谱 AI，可分析服务器状态、诊断问题、提供运维建议，支持多轮对话上下文，并支持多模型切换
- **风险检测**：多维度扫描（配置、资源、安全、日志、依赖、性能、证书、进程、网络等），支持严格模式、生产环境模式，可手动触发立即扫描
- **部署环境配置**：可自定义操作系统类型、公网 IP、防火墙、HTTPS、外部访问、自动封禁 IP、风险检测间隔、严格模式、生产模式等

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

### 1. 创建配置文件
复制  `config.json.example`  为  `config.json`  并按需修改。

```bash
cp config.json.example config.json
```

### 2. 配置 AI 助手（可选）
AI 助手需要智谱 AI 的 API 密钥。复制  `.env.example`  为  `.env`  并填写密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

#### 单模型配置（简单）
```env
AI_API_KEY=your_actual_api_key
AI_MODEL=glm-4-flash
AI_API_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions
```

#### 多模型配置（高级，支持前端切换）
```env
AI_MODELS='[{"name":"GLM-4-Flash","key":"your_key_1","url":"https://open.bigmodel.cn/api/paas/v4/chat/completions","model":"glm-4-flash"},{"name":"GLM-5.1","key":"your_key_2","url":"https://open.bigmodel.cn/api/paas/v4/chat/completions","model":"glm-5.1"}]'
```

如果不使用 AI 助手，可以不配置，面板其他功能正常。

### 3. 编辑服务配置
`config.json` 示例：

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
    "os_type": "",
    "production_mode": false,
    "strict_mode": false,
    "enable_auto_fix": false,
    "monitor_network_traffic": true,
    "configured": false,
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
- `deployment`：部署环境配置（影响风险检测策略和 AI 上下文）
  - `environment`：`intranet`（内网）或 `internet`（公网）
  - `has_public_ip`：是否有公网 IP
  - `firewall_enabled`：防火墙是否开启
  - `https_enabled`：是否启用 HTTPS
  - `allow_external_access`：是否允许外部访问
  - `auto_ban_ip`：是否自动封禁高频 IP（已移除封禁功能，保留字段）
  - `risk_check_interval`：风险检测间隔（秒）
  - `os_type`：操作系统类型（`windows`/`linux`/`macos`，留空自动检测）
  - `production_mode`：生产环境模式（提升风险严重性）
  - `strict_mode`：严格模式（更严格的风险阈值）
  - `enable_auto_fix`：启用自动修复建议（预留）
  - `monitor_network_traffic`：是否监控网络流量异常

## 运行

```bash
python app.py
```

启动后访问 `http://<服务器IP>:8888`。首次运行会弹出配置向导，完成后即可正常使用。

面板默认不输出访问日志，仅当发生错误时才有控制台输出。

## 相关图片展示

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 112519" src="https://github.com/user-attachments/assets/aff86b28-7daf-428e-940b-7d7c53d14a80" />

---

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 112539" src="https://github.com/user-attachments/assets/a116a55a-05a7-42e5-98e6-bc6497f5d376" />

---

<img width="1919" height="1078" alt="屏幕截图 2026-04-18 112554" src="https://github.com/user-attachments/assets/c9944bf0-3b8b-46b3-8cb9-265898bbed3d" />

---

<img width="1918" height="1079" alt="屏幕截图 2026-04-18 112612" src="https://github.com/user-attachments/assets/494d1936-69df-46ac-9ee7-b859609385a5" />

---

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 112625" src="https://github.com/user-attachments/assets/d0a4282f-6616-4d4c-aaf0-2435a77c0fd9" />

---

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 112643" src="https://github.com/user-attachments/assets/824fbcf6-e92d-47f7-b19c-b59532b10743" />

---

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 112655" src="https://github.com/user-attachments/assets/e1fa1837-33cf-4b2c-9941-f02aa73d7985" />

---

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 112708" src="https://github.com/user-attachments/assets/19165f2d-8d80-4d2e-b26b-e0adbc5f9def" />

---

<img width="1919" height="1079" alt="屏幕截图 2026-04-18 114428" src="https://github.com/user-attachments/assets/2daebf23-5afb-4dd4-b102-a0c5fdd471b3" />

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/services` | 获取所有服务状态（含 PID、维护模式等） |
| POST | `/api/services/{id}/start` | 启动服务 |
| POST | `/api/services/{id}/stop` | 停止服务 |
| POST | `/api/services/{id}/restart` | 重启服务 |
| POST | `/api/services/{id}/maintenance` | 设置维护模式（`{"enabled": true/false}`） |
| GET | `/api/services/{id}/logs` | 获取服务日志（默认最后 80 行） |
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
| POST | `/api/risks/scan` | 手动触发风险扫描 |
| GET | `/api/ai/models` | 获取可用的 AI 模型列表（用于前端切换） |
| POST | `/api/ai/chat` | AI 助手聊天接口（支持上下文和历史记录） |
| GET | `/api/ai/history` | 获取 AI 聊天历史 |

## 目录结构

```
service-control-panel/
├── app.py                 # 主入口
├── config.py              # 配置加载（含环境变量）
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
│   └── fonts/             # 字体文件（可选）
├── logs/                  # 服务日志（运行时创建）
├── pids/                  # PID 文件（运行时创建）
├── config.json.example    # 配置文件示例
├── .env.example           # 环境变量示例
├── maintenance.json       # 维护模式状态（运行时生成）
├── operations.jsonl       # 操作记录（运行时生成）
├── ai_chat_history.json   # AI 聊天历史（运行时生成）
└── requirements.txt       # Python 依赖
```

## 注意事项

- 维护模式开启后，服务会被停止且无法通过面板启动，直到手动关闭维护。
- 跨设备停止检测依赖 `operations.jsonl` 中的记录和本机 IP 对比（5 分钟内有效）。
- 如果未安装 `psutil`，部分监控功能不可用（建议安装）。
- 在 Windows 系统上，IP 地址详情通过调用 `ipconfig /all` 解析，支持显示临时 IPv6 地址和普通 IPv6 地址。
- 风险检测模块启动后立即执行首次扫描，界面会显示“正在扫描”，约 1-2 秒后展示结果。可在设置中调整检测间隔和严格模式。
- AI 助手需要有效的智谱 AI API 密钥，并确保服务器能访问 `https://open.bigmodel.cn`。聊天历史自动保存到 `ai_chat_history.json`，重启面板不会丢失。支持多模型切换，可在前端下拉菜单中选择不同模型。

## 开源协议

MIT License
