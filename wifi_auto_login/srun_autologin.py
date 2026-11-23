#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北京化工大学 (BUCT) 校园网 srun 认证网关 —— 断网自动登录守护脚本

原理（与 https://tree.buct.edu.cn 的 Portal.js 完全一致）:
  1) GET  /cgi-bin/get_challenge      拿 token(challenge)
  2) hmd5   = md5(token + password)                       (十六进制)
     info   = "{SRBX1}" + base64_custom( xxtea( JSON{username,password,ip,acid,enc_ver}, key=token ) )
     chksum = sha1(token+user+token+hmd5+token+ac_id+token+ip+token+n+token+type+token+info)
  3) GET  /cgi-bin/srun_portal?action=login&password={MD5}hmd5&info=...&chksum=...

用法:
  python srun_autologin.py              # 常驻守护：每 interval 秒检测一次，断网即登录
  python srun_autologin.py --once       # 只检测+必要时登录一次（适合任务计划每分钟跑）
  python srun_autologin.py --status     # 只打印当前在线状态
  python srun_autologin.py --login      # 忽略状态，强制登录一次
  python srun_autologin.py --verbose    # 打印详细日志

配置文件: 与本脚本同目录的 config.json
"""
import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "autologin.log")
LOCK_PATH = os.path.join(BASE_DIR, "autologin.lock")
LOG_MAX_BYTES = 2 * 1024 * 1024

DEFAULT_CONFIG = {
    "portal": "https://tree.buct.edu.cn",
    "ac_id": "20",
    "username": "",
    "password": "",
    "check_interval": 15,          # 在线时检测间隔(秒)
    "retry_interval": 20,          # 登录失败后的重试间隔(秒)
    "max_retry_interval": 300,     # 连续失败最大退避(秒)，防账号被锁
    "timeout": 8,                  # 单次 HTTP 超时(秒)
    "verify_ssl": False,           # 认证前证书可能是内网自签名
    "skip_if_public_ip": True,     # 出口 IP 是公网地址时（不在校园网）不尝试登录
    "device": "Windows 10",        # 上报的设备名（os 参数）
    "platform": "Windows",         # 上报的平台（name 参数）
}

CUSTOM_B64 = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
STD_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
B64_TABLE = str.maketrans(STD_B64, CUSTOM_B64)
DELTA = 0x9E3779B9
MASK = 0xFFFFFFFF

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #
class Log:
    verbose = False

    @staticmethod
    def _write(level, msg):
        line = "%s [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, msg)
        try:
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
                os.replace(LOG_PATH, LOG_PATH + ".1")
        except OSError:
            pass
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def info(msg):
    Log._write("INFO", msg)


def debug(msg):
    if Log.verbose:
        Log._write("DEBUG", msg)


def warn(msg):
    Log._write("WARN", msg)


def error(msg):
    Log._write("ERROR", msg)


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def load_config(require_credentials=True):
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        error("未找到配置文件，已生成模板：%s ，请填写 username / password 后重试" % CONFIG_PATH)
        sys.exit(2)
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg or {})
    if require_credentials and (not merged.get("username") or not merged.get("password")):
        error("config.json 里的 username / password 还没填")
        sys.exit(2)
    if require_credentials and "在这里填" in str(merged.get("password")):
        error("config.json 里的 password 还是占位文本，请改成真实密码")
        sys.exit(2)
    return merged


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
_SSL_CTX = None


def _ctx(verify):
    if verify:
        return ssl.create_default_context()
    if _SSL_CTX is None:
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        globals()["_SSL_CTX"] = c
    return _SSL_CTX


def http_get(url, timeout=8, verify=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": "https://tree.buct.edu.cn/srun_portal_pc?ac_id=20&theme=pro",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx(verify)) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_jsonp(text):
    """把 jsonp_123({...}) 解析成 dict"""
    text = (text or "").strip()
    if not text:
        return {}
    if not text.startswith("{"):
        i, j = text.find("("), text.rfind(")")
        if i != -1 and j > i:
            text = text[i + 1:j]
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"_data": obj}
    except ValueError:
        return {"_raw": text}


# --------------------------------------------------------------------------- #
# srun 加密
# --------------------------------------------------------------------------- #
def _str2long(s, with_len):
    """等价于 Portal.js 里的 s(a,b)：每 4 个字符压进一个 uint32（取字符低字节）"""
    raw = s.encode("utf-16-le")
    units = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]
    v = []
    for i in range(0, len(units), 4):
        val = 0
        for j, cu in enumerate(units[i:i + 4]):
            val |= cu << (8 * j)
        v.append(val & MASK)
    if with_len:
        v.append(len(units))
    return v


def _long2bytes(v):
    out = bytearray()
    for x in v:
        out += (x & MASK).to_bytes(4, "little")
    return bytes(out)


def xxtea_encrypt(plain, key):
    v = _str2long(plain, True)
    k = _str2long(key, False)
    while len(k) < 4:
        k.append(0)
    n = len(v) - 1
    if n < 1:
        return _long2bytes(v)
    z, y = v[n], v[0]
    q = 6 + 52 // (n + 1)
    d = 0
    p = 0
    while q > 0:
        q -= 1
        d = (d + DELTA) & MASK
        e = (d >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            m = ((z >> 5) ^ ((y << 2) & MASK))
            m = (m + (((y >> 3) ^ ((z << 4) & MASK)) ^ (d ^ y))) & MASK
            m = (m + ((k[(p & 3) ^ e] ^ z) & MASK)) & MASK
            z = v[p] = (v[p] + m) & MASK
        y = v[0]
        m = ((z >> 5) ^ ((y << 2) & MASK))
        m = (m + (((y >> 3) ^ ((z << 4) & MASK)) ^ (d ^ y))) & MASK
        m = (m + ((k[(n & 3) ^ e] ^ z) & MASK)) & MASK
        z = v[n] = (v[n] + m) & MASK
    return _long2bytes(v)


def encode_info(obj, token):
    plain = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    cipher = xxtea_encrypt(plain, token)
    b64 = base64.b64encode(cipher).decode("ascii").translate(B64_TABLE)
    return "{SRBX1}" + b64


def md5_hex(s):
    """等价于 JS md5(token, password) -> hex(md5(token_bytes + password_bytes))"""
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def sha1_hex(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 门户交互
# --------------------------------------------------------------------------- #
def portal_url(cfg, path):
    return cfg["portal"].rstrip("/") + path


def query_status(cfg):
    """返回 (是否在线, 详情字典)。请求异常时抛出。"""
    ts = int(time.time() * 1000)
    url = portal_url(cfg, "/cgi-bin/rad_user_info?callback=jsonp_%d&_=%d" % (ts, ts))
    data = parse_jsonp(http_get(url, cfg["timeout"], cfg["verify_ssl"]))
    debug("rad_user_info -> %s" % json.dumps(data, ensure_ascii=False)[:400])
    return data.get("error") == "ok", data


def get_client_ip(cfg, data):
    for k in ("client_ip", "online_ip", "online_ip6"):
        ip = (data or {}).get(k)
        if ip and ip not in ("::", "0.0.0.0"):
            return ip
    # 兜底：从门户页面 CONFIG 里抓 ip
    for path in ("/srun_portal_pc?ac_id=%s&theme=pro" % cfg["ac_id"],
                 "/srun_portal_success?ac_id=%s&theme=basic" % cfg["ac_id"],
                 "/"):
        try:
            html = http_get(portal_url(cfg, path), cfg["timeout"], cfg["verify_ssl"])
        except Exception:
            continue
        m = re.search(r'ip\s*:\s*"([0-9a-fA-F\.:]+)"', html)
        if m and m.group(1) not in ("", "::", "0.0.0.0"):
            return m.group(1)
    return ""


def get_challenge(cfg, ip):
    ts = int(time.time() * 1000)
    q = urllib.parse.urlencode({
        "callback": "jsonp_%d" % ts,
        "username": cfg["username"],
        "ip": ip,
        "_": ts,
    })
    data = parse_jsonp(http_get(portal_url(cfg, "/cgi-bin/get_challenge?" + q),
                                cfg["timeout"], cfg["verify_ssl"]))
    debug("get_challenge -> %s" % json.dumps(data, ensure_ascii=False)[:300])
    token = data.get("challenge")
    if not token:
        raise RuntimeError("获取 token 失败: %s" % (data.get("error_msg") or data.get("error") or data))
    return token, data


def _is_private_ip(ip):
    try:
        import ipaddress
        return ipaddress.ip_address(ip).is_private
    except Exception:
        return False


def do_login(cfg):
    """执行一次登录，返回 (成功?, message)"""
    ip = ""
    try:
        online, data = query_status(cfg)
    except Exception as e:
        debug("rad_user_info 请求失败: %s" % e)
        online, data = False, {}
    if online:
        return True, "当前已在线，无需登录"

    ip = get_client_ip(cfg, data)
    if ip and cfg.get("skip_if_public_ip", True) and not _is_private_ip(ip):
        return False, "出口 IP %s 是公网地址，当前不在校园网内，跳过登录" % ip
    token, ch = get_challenge(cfg, ip)
    if not ip:
        ip = ch.get("client_ip") or ""
    if not ip:
        return False, "无法确定本机在校园网内的 IP"

    ac_id = str(cfg["ac_id"])
    username = cfg["username"]
    password = cfg["password"]
    n, typ = "200", "1"

    hmd5 = md5_hex(token + password)
    info_str = encode_info({
        "username": username,
        "password": password,
        "ip": ip,
        "acid": ac_id,
        "enc_ver": "srun_bx1",
    }, token)

    chk = token + username
    chk += token + hmd5
    chk += token + ac_id
    chk += token + ip
    chk += token + n
    chk += token + typ
    chk += token + info_str
    chksum = sha1_hex(chk)

    ts = int(time.time() * 1000)
    q = urllib.parse.urlencode({
        "callback": "jsonp_%d" % ts,
        "action": "login",
        "username": username,
        "password": "CHANGE_ME" + hmd5,
        "os": cfg["device"],
        "name": cfg["platform"],
        "double_stack": "0",
        "chksum": chksum,
        "info": info_str,
        "ac_id": ac_id,
        "ip": ip,
        "n": n,
        "type": typ,
        "_": ts,
    }, quote_via=urllib.parse.quote)
    resp = parse_jsonp(http_get(portal_url(cfg, "/cgi-bin/srun_portal?" + q),
                                cfg["timeout"], cfg["verify_ssl"]))
    debug("srun_portal -> %s" % json.dumps(resp, ensure_ascii=False)[:400])

    ok = resp.get("error") == "ok" or resp.get("suc_msg") == "login_ok" or resp.get("res") == "ok"
    if ok or resp.get("error") in ("ip_already_online_error",):
        # 复核
        try:
            verified, _ = query_status(cfg)
        except Exception:
            verified = True
        return (True, "登录成功 (ip=%s)" % ip) if verified or ok else (False, "服务器返回 ok 但复核未在线")

    msg = resp.get("error_msg") or resp.get("error") or resp.get("_raw") or str(resp)
    if resp.get("ecode") not in (None, 0, "0"):
        msg = "%s (ecode=%s)" % (msg, resp.get("ecode"))
    return False, "登录失败: %s" % msg


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def ensure_online(cfg):
    """检测一次，必要时登录。返回 True 表示已在线。"""
    try:
        online, data = query_status(cfg)
    except Exception as e:
        warn("网络探测失败（可能完全不联通）: %s" % e)
        return False
    if online:
        debug("在线: user=%s ip=%s 流量=%s MB" % (
            data.get("user_name"), data.get("online_ip"),
            round(int(data.get("all_bytes") or 0) / 1048576.0, 1)))
        return True
    if data.get("error") == "not_online_error":
        info("检测到未认证（ip=%s），开始登录…" % (data.get("client_ip") or "?"))
    else:
        info("在线探测返回异常（%s），尝试登录…" % (data.get("error") or data))
    ok, msg = do_login(cfg)
    (info if ok else error)(msg)
    return ok


def acquire_single_instance():
    """文件锁：同一时间只允许一个守护进程（返回文件句柄需保持不关闭）"""
    try:
        f = open(LOCK_PATH, "a+")
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        try:
            f.close()
        except OSError:
            pass
        return False


def run_loop(cfg):
    interval = max(5, int(cfg["check_interval"]))
    retry = max(5, int(cfg["retry_interval"]))
    max_retry = max(retry, int(cfg["max_retry_interval"]))
    fails = 0
    info("守护启动：%s  账号=%s  ac_id=%s  检测间隔=%ss" % (
        cfg["portal"], cfg["username"], cfg["ac_id"], interval))
    while True:
        try:
            ok = ensure_online(cfg)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            ok = False
            error("异常: %s" % e)
        if ok:
            fails = 0
            time.sleep(interval)
        else:
            fails += 1
            wait = min(max_retry, retry * (2 ** min(fails - 1, 4)))
            if fails >= 3:
                warn("已连续失败 %d 次，退避 %ds 后重试（避免账号被锁）" % (fails, wait))
            else:
                info("%ds 后重试" % wait)
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser(description="BUCT 校园网 srun 自动登录")
    ap.add_argument("--once", action="store_true", help="只检测/登录一次")
    ap.add_argument("--status", action="store_true", help="只打印在线状态")
    ap.add_argument("--login", action="store_true", help="强制登录一次")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    args = ap.parse_args()

    Log.verbose = args.verbose
    cfg = load_config(require_credentials=not args.status)

    if args.status:
        try:
            online, data = query_status(cfg)
        except Exception as e:
            print("探测失败: %s" % e)
            sys.exit(1)
        if online:
            print("在线  用户=%s  IP=%s  已用=%s MB  套餐=%s" % (
                data.get("user_name"), data.get("online_ip"),
                round(int(data.get("all_bytes") or 0) / 1048576.0, 1),
                data.get("products_name")))
            sys.exit(0)
        print("未认证  error=%s  client_ip=%s" % (data.get("error"), data.get("client_ip")))
        sys.exit(3)

    if args.login:
        ok, msg = do_login(cfg)
        (info if ok else error)(msg)
        sys.exit(0 if ok else 1)

    if args.once:
        ok = ensure_online(cfg)
        sys.exit(0 if ok else 1)

    lock = acquire_single_instance()
    if lock is False:
        info("已有守护进程在运行，本次启动忽略")
        sys.exit(0)

    try:
        run_loop(cfg)
    except KeyboardInterrupt:
        info("已退出")


if __name__ == "__main__":
    main()
