# -*- coding: utf-8 -*-
"""UI 截图自测：进程内起服务 -> 无头 Edge 截图 -> 关闭（不常驻）"""
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from werkzeug.serving import make_server  # noqa
import app as A  # noqa

PORT = 5056
W = sys.argv[1] if len(sys.argv) > 1 else '1600'
H = sys.argv[2] if len(sys.argv) > 2 else '950'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   'ui_shot_%sx%s.png' % (W, H))

srv = make_server('127.0.0.1', PORT, A.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
A.comfy.start()
time.sleep(1)

edge = None
for p in [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
          r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']:
    if os.path.isfile(p):
        edge = p
        break
print('edge =', edge)

try:
    if edge:
        cmd = [edge, '--headless=new', '--disable-gpu', '--hide-scrollbars',
               '--virtual-time-budget=9000', f'--window-size={W},{H}',
               f'--screenshot={OUT}', f'http://127.0.0.1:{PORT}/']
        subprocess.run(cmd, timeout=60, capture_output=True)
        print('screenshot ->', OUT, os.path.getsize(OUT) if os.path.exists(OUT) else 'MISSING')
    else:
        print('未找到 msedge')
finally:
    srv.shutdown()
print('done')
