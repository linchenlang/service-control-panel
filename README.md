# 服务控制面板

一个基于 Python Flask 开发的 Web 服务管理面板，用于集中启动、停止、重启多个服务，并提供实时系统资源监控、HTTP 请求频率统计、跨设备操作记录等功能。

## 功能特性

- 🔧 **多服务管理** – 启动、停止、重启、维护模式
- 📊 **系统监控** – CPU、内存、磁盘、网络流量实时曲线
- 📈 **请求频率统计** – 基于日志分析每5秒的 HTTP 请求量
- 🌐 **跨设备记录** – 记录每次操作来源 IP，自动检测非本面板的停止操作
- 🔔 **异常告警** – 服务意外停止时弹窗提醒
- ⚙️ **动态配置** – 在 Web 界面中添加/编辑/删除服务，热重载生效

环境要求

- Python 3.8+
- 支持 Windows / Linux / macOS

## 相关截图展示

<img width="1919" height="1079" alt="屏幕截图 2026-04-05 180741" src="https://github.com/user-attachments/assets/9b618e5e-11f0-4b0b-b6f3-f8dc472669de" />

<img width="1919" height="1076" alt="屏幕截图 2026-04-05 180548" src="https://github.com/user-attachments/assets/d56d327a-58cf-4bfa-81a0-ffa0c1ff5087" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-05 180700" src="https://github.com/user-attachments/assets/232a89a2-70b6-4e5e-9268-52b17f597e80" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-05 180713" src="https://github.com/user-attachments/assets/503578b1-f038-44c6-99a5-6c4920bfcdcf" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-05 180725" src="https://github.com/user-attachments/assets/cd36c395-08a6-42b0-8e33-4f3757fada96" />

<img width="1919" height="1079" alt="屏幕截图 2026-04-05 180732" src="https://github.com/user-attachments/assets/e9995b50-26c9-42c5-b03c-5db7e3e25baf" />


## 安装

```bash
git clone https://github.com/linchenlang/service-control-panel.git
cd service-control-panel
pip install -r requirements.txt
```
g
## 配置

编辑 `config.json`：

| 字段 | 说明 |
|------|------|
| `panel_host` | 面板监听地址（默认 `0.0.0.0`） |
| `panel_port` | 面板端口（默认 `8888`） |
| `logs_dir` | 日志存放目录 |
| `services` | 需要管理的服务列表 |

每个服务配置项：

```json
{
  "id": "唯一标识",
  "name": "显示名称",
  "command": "python3 app.py" 或 ["python3", "app.py"],
  "cwd": "工作目录（相对或绝对路径）",
  "port": 服务端口（可选）
}
```

> 注意：使用相对路径时，相对于面板程序所在目录。

## 运行

```bash
python panel.py
```

启动后访问 `http://服务器IP:8888` 即可使用面板。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/services` | 获取所有服务状态 |
| POST | `/api/services/{id}/start` | 启动服务 |
| POST | `/api/services/{id}/stop` | 停止服务 |
| POST | `/api/services/{id}/restart` | 重启服务 |
| POST | `/api/services/{id}/maintenance` | 设置维护模式 |
| GET | `/api/services/{id}/logs` | 获取服务日志（默认最后15行） |
| GET | `/api/dashboard_stats` | 获取系统资源（CPU/内存/磁盘） |
| GET | `/api/traffic/{id}` | 获取服务请求频率历史 |
| GET | `/api/service_configs` | 获取服务配置列表 |
| POST/PUT/DELETE | `/api/service_configs` | 增删改服务配置 |

## 目录结构

```
service-control-panel/
├── panel.py              # 主程序
├── config.json           # 配置文件
├── requirements.txt      # Python 依赖
├── templates/
│   └── index.html        # 前端页面
├── static/
│   ├── style.css         # 样式表
│   └── fonts             #字体文件夹
│       └── FZXiaoBiaoSong.ttf     #字体（方正小标宋）文件
├── logs/                 # 服务日志（运行时自动生成）
├── pids/                 # PID 文件（运行时）
└── operations.jsonl      # 操作记录（运行时）
```

## 注意事项

- 维护模式开启后，服务会被停止且无法通过面板启动，直到手动关闭维护。
- 跨设备停止检测依赖于 `operations.jsonl` 中的记录和本地 IP 对比。
- 请确保 `psutil` 库已安装，否则部分监控功能不可用。

## 开源协议

MIT License
