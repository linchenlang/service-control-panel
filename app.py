import logging
import sys
from flask import Flask
from api import api
from config import PANEL_HOST, PANEL_PORT

# 彻底关闭 Werkzeug 的访问日志
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# 也可以将 stdout/stderr 重定向到 null（完全静默）
# sys.stdout = open(os.devnull, 'w')
# sys.stderr = open(os.devnull, 'w')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.register_blueprint(api)

if __name__ == "__main__":
    # 清理僵死 PID
    from service_manager import get_status
    from config import SERVICES
    for svc in SERVICES:
        get_status(svc["id"])
    # 禁用 Flask 内置的请求日志
    app.logger.disabled = True
    # 使用普通 run，不打印任何启动信息（可选）
    app.run(host=PANEL_HOST, port=PANEL_PORT, debug=False, threaded=True)
