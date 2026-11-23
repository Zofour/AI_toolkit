# -*- coding: utf-8 -*-
"""把 Android 端 Crypto 的 Java 输出与 Python 参考实现逐字段比对"""
import io, os, subprocess, sys

sys.path.insert(0, r"C:\chatbox_temp\wifi_auto_login")
import srun_autologin as S

JDK = r"C:\chatbox_temp\chatbox-bridge\tools\jdk17\bin\java.exe"
OUT = r"C:\chatbox_temp\wifi_auto_login\android\_verify\out"

raw = subprocess.run([JDK, "-Dfile.encoding=UTF-8", "-cp", OUT, "com.chatbox.buctwifi.CryptoTest"],
                     capture_output=True)
text = raw.stdout.decode("utf-8", "replace")
if raw.returncode != 0:
    print(text)
    print(raw.stderr.decode("utf-8", "replace"))
    sys.exit(1)

token = "e3ae3733b4f01dcbcbf7d46e0d90be06cca99b72703648567eec4aa60ca5c103"
cases = [
    ("2025000000", "Test@123", "10.0.0.1", "20"),
    ("2025000000", "a" * 37, "10.0.0.1", "20"),
    ("2025000000", "p@ss w/ 中文&符号", "10.0.0.1", "20"),
]

# 解析 java 输出
java = []
block = None
for line in text.splitlines():
    if line.startswith("PW="):
        block = {"pw": line[3:]}
    elif line.strip().startswith("info="):
        block["info"] = line.strip()[5:]
    elif line.strip().startswith("hmd5="):
        block["hmd5"] = line.strip()[5:]
    elif line.strip().startswith("chksum="):
        block["chksum"] = line.strip()[7:]
        java.append(block)

allok = True
for (user, pw, ip, acid), j in zip(cases, java):
    info = S.encode_info({"username": user, "password": pw, "ip": ip, "acid": acid,
                          "enc_ver": "srun_bx1"}, token)
    hmd5 = S.md5_hex(token + pw)
    chk = token + user + token + hmd5 + token + acid + token + ip + token + "200" + token + "1" + token + info
    chksum = S.sha1_hex(chk)
    ok = (info == j.get("info") and hmd5 == j.get("hmd5") and chksum == j.get("chksum"))
    allok &= ok
    print("pw=%-14r  info=%s  md5=%s  chksum=%s" % (pw, info == j.get("info"),
                                                    hmd5 == j.get("hmd5"), chksum == j.get("chksum")))
    if not ok:
        print("  py info:", info)
        print("  java    :", j.get("info"))
        print("  py  md5 :", hmd5, " java:", j.get("hmd5"))
        print("  py  chk :", chksum, " java:", j.get("chksum"))

print("ALL MATCH (Java/Android == Python/门户 JS)" if allok else "MISMATCH")
sys.exit(0 if allok else 1)
