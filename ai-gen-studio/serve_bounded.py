# -*- coding: utf-8 -*-
"""限时服务器：跑 100 秒后自动退出，避免留下常驻进程。
同时把每个请求写进 _server_hits.log，方便确认手机是否连上。"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A  # noqa
from flask import request  # noqa

HITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_server_hits.log')


def boom():
    time.sleep(100)
    print('[bounded] 到时退出', flush=True)
    os._exit(0)


threading.Thread(target=boom, daemon=True).start()


@A.app.before_request
def _log_hit():
    try:
        with open(HITS, 'a', encoding='utf-8') as f:
            f.write('%s  %-16s %s\n' % (time.strftime('%H:%M:%S'), request.remote_addr, request.path))
    except Exception:
        pass


ip = A.tailscale_ip()
A.comfy.start()
print('[bounded] http://%s:8848' % ip, flush=True)
A.app.run(host=ip, port=8848, threaded=True, debug=False)
