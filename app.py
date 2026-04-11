import logging
from logging.handlers import RotatingFileHandler
import sys
from flask import Flask
from api import api
from config import PANEL_HOST, PANEL_PORT

# 配置面板自身日志
panel_log_handler = RotatingFileHandler('panel.log', maxBytes=1024*1024, backupCount=3, encoding='utf-8')
panel_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
panel_log_handler.setLevel(logging.DEBUG)

# 根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(panel_log_handler)

# 控制台也输出错误（便于调试）
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.ERROR)
root_logger.addHandler(console_handler)

# 降低 Werkzeug 访问日志级别，错误仍会输出
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.register_blueprint(api)

# 确保 Flask 应用日志也写入文件
app.logger.addHandler(panel_log_handler)
app.logger.setLevel(logging.DEBUG)

if __name__ == "__main__":
    from service_manager import get_status
    from config import SERVICES
    for svc in SERVICES:
        get_status(svc["id"])
    app.run(host=PANEL_HOST, port=PANEL_PORT, debug=False, threaded=True)
