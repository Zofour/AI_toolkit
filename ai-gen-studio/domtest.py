# -*- coding: utf-8 -*-
"""把页面渲染后的真实 DOM 拉出来，检查模型下拉框里有哪些选项。"""
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from werkzeug.serving import make_server  # noqa
import app as A  # noqa

PORT = 5057
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

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_dom.html')
try:
    cmd = [edge, '--headless=new', '--disable-gpu', '--virtual-time-budget=9000',
           '--dump-dom', f'http://127.0.0.1:{PORT}/']
    r = subprocess.run(cmd, timeout=70, capture_output=True)
    html = r.stdout.decode('utf-8', 'ignore')
    open(out, 'w', encoding='utf-8').write(html)
    m = re.search(r'<select id="textModel".*?</select>', html, re.S)
    if m:
        opts = re.findall(r'<option[^>]*>([^<]*)</option>', m.group(0))
        print(f'textModel 下拉框选项数 = {len(opts)}')
        for o in opts:
            print('   -', o)
        print()
        print('包含新模型 qwen3.8? ->', any('qwen3.8' in o for o in opts))
    else:
        print('没找到 textModel select；DOM 长度', len(html))
    m2 = re.search(r'<select id="imageModel".*?</select>', html, re.S)
    if m2:
        print('\nimageModel 选项:')
        for o in re.findall(r'<option[^>]*>([^<]*)</option>', m2.group(0)):
            print('   -', o)
finally:
    srv.shutdown()
