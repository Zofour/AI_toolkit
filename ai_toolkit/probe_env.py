# -*- coding: utf-8 -*-
"""环境自检：一条命令摸清本机工具链，输出精简摘要（替代多轮人工探测）。

用法:
    python C:\\chatbox_temp\\ai_toolkit\\probe_env.py          # 人类可读摘要
    python C:\\chatbox_temp\\ai_toolkit\\probe_env.py --json    # 机器可读 JSON
"""
import sys, os, json, shutil, importlib.util, subprocess, platform

PYLIBS = ['torch', 'onnx', 'onnxruntime', 'nncase', 'docx', 'lxml', 'latex2mathml',
          'PIL', 'numpy', 'cv2', 'serial', 'requests', 'transformers', 'diffusers',
          'openai', 'pandas', 'openpyxl', 'sklearn', 'matplotlib', 'pymupdf']
CLIS = ['node', 'npm', 'pnpm', 'git', 'ffmpeg', 'java', 'dotnet', 'docker', 'wsl',
        'code', 'uv', 'uvx', 'nvidia-smi', 'tar', 'ssh', 'scp', '7z']
XSL = r'C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL'


def _mods(names):
    ok = []
    for m in names:
        try:
            if importlib.util.find_spec(m):
                ok.append(m)
        except Exception:
            pass
    return ok


def _ram():
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / 1024 ** 3, 1)
    except Exception:
        return None


def collect():
    d = {'os': platform.platform(), 'py': platform.python_version(), 'ram_gb': _ram()}
    d['pylibs'] = _mods(PYLIBS)
    d['pylibs_missing'] = [m for m in PYLIBS if m not in d['pylibs']]
    d['cli'] = {c: shutil.which(c) for c in CLIS}
    try:
        import torch
        d['torch'] = torch.__version__
        d['cuda'] = bool(torch.cuda.is_available())
        d['gpu'] = torch.cuda.get_device_name(0) if d['cuda'] else None
    except Exception:
        pass
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            '[System.IO.Ports.SerialPort]::GetPortNames() -join ","'],
                           capture_output=True, text=True, timeout=25)
        d['ports'] = [p for p in r.stdout.strip().split(',') if p]
    except Exception:
        d['ports'] = None
    d['omath_xsl'] = os.path.exists(XSL)
    return d


def main():
    d = collect()
    if '--json' in sys.argv:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return
    print('OS   :', d['os'])
    print('PY   :', d['py'], '| RAM', d['ram_gb'], 'GB | GPU', d.get('gpu'), '(cuda', d.get('cuda'), ')')
    print('LIBS :', ','.join(d['pylibs']))
    if d['pylibs_missing']:
        print('MISS :', ','.join(d['pylibs_missing']))
    print('CLI  :', ','.join(k for k, v in d['cli'].items() if v))
    print('NOCLI:', ','.join(k for k, v in d['cli'].items() if not v) or '-')
    print('PORT :', ','.join(d['ports']) if d['ports'] else '(none)')
    print('OMath:', 'XSL ok' if d['omath_xsl'] else 'XSL MISSING')


if __name__ == '__main__':
    main()
