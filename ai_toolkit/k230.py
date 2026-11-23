# -*- coding: utf-8 -*-
"""K230 / CanMV 板子助手：串口 raw REPL 执行 + MTP 秒级传大文件。

动机：串口试错的原始输出极啰嗦、要反复用 —— 封装成一条命令，中间过程不进上下文。

用法:
    python k230.py ports                                  # 列串口，标出 K230(VID_1209/PID_ABD1)
    python k230.py exec "import os;print(os.listdir('/sdcard'))"
    python k230.py run board_script.py                    # 把本地 py 送上板执行(小文件走 REPL)
    python k230.py ls /sdcard
    python k230.py cat /sdcard/app/main.py
    python k230.py put x.kmodel /sdcard/app/tests/kmodel/x.kmodel   # 大文件走 MTP(秒级,二进制安全)
    python k230.py reset                                  # machine.reset()
可选: --port COMx 强制指定串口；--baud 115200

坑(来自实测，勿踩):
  - CanMV IDE 会独占串口，用前先 Stop-Process canmvide。
  - 硬复位后 COM 口会消失约 25~40s 才回来。
  - 大 kmodel 千万别走 REPL 上传，必须用 put(MTP)。
  - 板上 Python 堆极小(~3.8MB)，循环内避免大临时分配，否则整板复位。
注意: 本脚本的 exec/ls/cat/reset 已按 raw REPL 协议实现；put 依赖 CanMV 的 MTP 盘符，
      需板子以 MTP 设备 "CanMV" 出现时才有效（无硬件时无法自测，请以板上实测结果为准）。
"""
import os
import sys
import time

BAUD = 115200
VIDPID = (0x1209, 0xABD1)


# ---------- 串口发现 ----------
def list_ports():
    from serial.tools import list_ports as lp
    rows = []
    for p in lp.comports():
        isk = (p.vid, p.pid) == VIDPID
        rows.append((p.device, p.description, isk))
    return rows


def find_board(explicit=None):
    if explicit:
        return explicit
    rows = list_ports()
    for dev, desc, isk in rows:
        if isk:
            return dev
    # 退而求其次：逐个端口探测 raw REPL
    for dev, desc, _ in rows:
        try:
            if probe(dev):
                return dev
        except Exception:
            pass
    return None


def probe(port, baud=BAUD):
    import serial
    ser = serial.Serial(port, baud, timeout=0.2)
    try:
        ser.write(b'\r\x03\x03')
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.write(b'\x01')
        return b'raw REPL' in _read_until(ser, b'raw REPL', 1.5)
    finally:
        try:
            ser.write(b'\x02')
        except Exception:
            pass
        ser.close()


# ---------- raw REPL ----------
def _read_until(ser, marker, timeout):
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = ser.read(512)
        if d:
            buf += d
            if marker in buf:
                break
        else:
            time.sleep(0.01)
    return bytes(buf)


def _dec(b):
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('gbk', 'replace')


def _write_code(ser, code, piece=1024, pause=0.004):
    """分块节流写，避免 USB CDC 大块写入丢字节（实测丢字节会导致 SyntaxError）。"""
    b = code.encode('utf-8')
    for i in range(0, len(b), piece):
        ser.write(b[i:i + piece])
        time.sleep(pause)


def exec_code(port, code, timeout=30, baud=BAUD):
    """在板上执行一段代码，返回 (stdout, stderr)。"""
    import serial
    ser = serial.Serial(port, baud, timeout=0.2)
    try:
        ser.write(b'\r\x03\x03')
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.write(b'\x01')
        _read_until(ser, b'raw REPL', 2.0)
        _read_until(ser, b'>', 2.0)
        _write_code(ser, code)
        ser.write(b'\x04')
        data = _read_until(ser, b'\x04>', timeout)
        if data.startswith(b'OK'):
            data = data[2:]
        i = data.find(b'\x04')
        out = data[:i] if i >= 0 else data
        rest = data[i + 1:] if i >= 0 else b''
        j = rest.find(b'\x04')
        err = rest[:j] if j >= 0 else rest
        return _dec(out), _dec(err)
    finally:
        try:
            ser.write(b'\x02')
        except Exception:
            pass
        ser.close()


def push_file(port, local, remote, chunk=1200, baud=BAUD, verify_md5=False):
    """经 raw REPL 把 local 写到板上 remote（可覆盖）。
    ⭐ 实测约束：板端 raw REPL **一个程序的源码必须 < ~2000 字符**
    （行数不限；超过就报 SyntaxError：单行 4000 字符会被截断、多行超长也报错），
    且**大块写入会丢字节**（要分块节流）。所以这里：
      · 把 base64 拆成每块 chunk 字节（程序 ~1.6KB < 2KB）
      · **一次开串口、连续灌所有块**（不再每块重新开串口/握手，快很多）
      · 首块 open('wb')，末块 close()，中间复用全局 f
    返回 (ok, info)。"""
    import base64
    import serial
    import hashlib
    port = port or find_board()
    if not port:
        return False, '未找到 K230 串口'
    data = open(local, 'rb').read()
    pieces = [base64.b64encode(data[i:i + chunk]).decode()
              for i in range(0, len(data), chunk)]
    if not pieces:
        return False, '空文件'
    ser = serial.Serial(port, baud, timeout=0.2)
    n = 0
    try:
        ser.write(b'\r\x03\x03')
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.write(b'\x01')
        _read_until(ser, b'raw REPL', 2.0)
        _read_until(ser, b'>', 2.0)
        for i, b64 in enumerate(pieces):
            if i == 0:
                code = "import ubinascii;f=open('%s','wb');" % remote
            else:
                code = ""
            code += "f.write(ubinascii.a2b_base64('%s'))" % b64
            if i == len(pieces) - 1:
                code += ";f.close()"
            ser.write(code.encode() + b'\x04')
            r = _read_until(ser, b'\x04>', 20)
            if b'Error' in r or b'Traceback' in r:
                try:
                    ser.write(b"f.close()\x04")
                    _read_until(ser, b'\x04>', 5)
                except Exception:
                    pass
                return False, '块 %d 失败: %s' % (i, r.decode(errors='replace')[-160:])
            n += 1
    finally:
        try:
            ser.write(b'\x02')
        except Exception:
            pass
        ser.close()
    # 校验
    out, err = exec_code(port, "import os;print(os.stat('%s')[6])" % remote)
    got = (out or '').strip().rstrip('>')
    ok = (got == str(len(data)))
    info = 'blocks=%d board=%s local=%d' % (n, got, len(data))
    if ok and verify_md5:
        want = hashlib.md5(data).hexdigest()
        out2, _ = exec_code(
            port,
            ("import uhashlib;f=open('%s','rb');h=uhashlib.md5()" % remote)
            + "\nwhile True:\n d=f.read(4096)\n if not d: break\n h.update(d)\n"
            + "f.close();print(''.join(['%02x' % b for b in h.digest()]))")
        got2 = (out2 or '').strip().rstrip('>')
        ok = (got2 == want)
        info += ' md5=%s' % ('ok' if ok else 'MISMATCH(%s vs %s)' % (got2, want))
    return ok, info


# ---------- MTP 传文件 ----------
def mtp_put(local, remote):
    """通过 CanMV 的 MTP 盘把 local 拷到 remote（如 /sdcard/app/x.kmodel）。"""
    import subprocess
    parts = [p for p in remote.replace('\\', '/').split('/') if p]
    if not parts:
        raise ValueError('remote 路径无效: %s' % remote)
    ps_parts = ','.join("'" + p + "'" for p in parts[:-1]) or "''"
    name = os.path.basename(local)
    script = """
$ErrorActionPreference='Stop'
$sh = New-Object -ComObject Shell.Application
$pc = $sh.NameSpace(17)
$dev = $pc.Items() | Where-Object { $_.Name -eq 'CanMV' } | Select-Object -First 1
if(-not $dev){ Write-Output 'NO_DEVICE(板子未以MTP出现)'; exit 2 }
$cur = $dev.GetFolder
foreach($p in @(%s)){
  $nx = $cur.Items() | Where-Object { $_.Name -eq $p } | Select-Object -First 1
  if(-not $nx){ Write-Output ('NO_DIR:'+$p); exit 3 }
  $cur = $nx.GetFolder
}
$cur.CopyHere('%s', 16)
Start-Sleep -Milliseconds 1500
$fi = $cur.Items() | Where-Object { $_.Name -eq '%s' } | Select-Object -First 1
if($fi){ Write-Output ('OK size=' + $fi.Size) } else { Write-Output 'COPY_FAILED' }
""" % (ps_parts, local, name)
    r = subprocess.run(['powershell', '-NoProfile', '-Command', script],
                       capture_output=True, text=True)
    return (r.stdout or '') + (r.stderr or '')


# ---------- CLI ----------
def main(argv):
    port = None
    baud = BAUD
    args = []
    i = 1
    while i < len(argv):
        if argv[i] == '--port':
            port = argv[i + 1]; i += 2
        elif argv[i] == '--baud':
            baud = int(argv[i + 1]); i += 2
        else:
            args.append(argv[i]); i += 1
    if not args:
        print(__doc__); return 2
    cmd = args[0]

    if cmd == 'ports':
        for dev, desc, isk in list_ports():
            print(('* ' if isk else '  ') + dev, '|', desc, '| K230' if isk else '')
        return 0

    if cmd == 'put':
        print(mtp_put(args[1], args[2]))
        return 0

    if cmd == 'push':
        ok, info = push_file(port, args[1], args[2])
        print(('OK ' if ok else 'FAIL ') + info)
        return 0 if ok else 1

    dev = find_board(port)
    if not dev:
        print('未找到 K230 串口。可用 --port COMx 指定；或先 Stop-Process canmvide。')
        return 1
    print('# port:', dev)

    if cmd == 'exec':
        out, err = exec_code(dev, args[1], baud=baud)
    elif cmd == 'run':
        with open(args[1], encoding='utf-8') as f:
            out, err = exec_code(dev, f.read(), baud=baud)
    elif cmd == 'ls':
        path = args[1] if len(args) > 1 else '/sdcard'
        out, err = exec_code(dev, "import os;print('\\n'.join(os.listdir('%s')))" % path, baud=baud)
    elif cmd == 'cat':
        out, err = exec_code(dev, "print(open('%s').read())" % args[1], baud=baud)
    elif cmd == 'reset':
        try:
            exec_code(dev, 'import machine;machine.reset()', timeout=3, baud=baud)
        except Exception:
            pass
        print('reset sent (COM 口将消失约 25~40s)')
        return 0
    else:
        print(__doc__); return 2

    if out:
        print(out, end='' if out.endswith('\n') else '\n')
    if err.strip():
        print('[stderr]', err, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
