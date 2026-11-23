# -*- coding: utf-8 -*-
import json, sys, subprocess, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import srun_autologin as S

CASES = [
    ("e3ae3733b4f01dcbcbf7d46e0d90be06cca99b72703648567eec4aa60ca5c103",
     {"username": "2025000000", "password": "CHANGE_ME", "ip": "10.0.0.1", "acid": "20", "enc_ver": "srun_bx1"}),
    ("abc123",
     {"username": "2025000000", "password": "a" * 37, "ip": "10.0.0.1", "acid": "20", "enc_ver": "srun_bx1"}),
    ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
     {"username": "2025000000", "password": "CHANGE_ME", "ip": "10.0.0.1", "acid": "20", "enc_ver": "srun_bx1"}),
]

ok_all = True
for token, obj in CASES:
    plain = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    py_info = S.encode_info(obj, token)
    py_hmd5 = S.md5_hex(token + obj["password"])
    chk = token + obj["username"] + token + py_hmd5 + token + obj["acid"] + token + obj["ip"] \
        + token + "200" + token + "1" + token + py_info
    py_chk = S.sha1_hex(chk)

    out = subprocess.check_output(["node", os.path.join(os.path.dirname(os.path.abspath(__file__)), "_js_ref.js"),
                                   token, plain], text=True, encoding="utf-8")
    js = json.loads(out)
    same_info = js["info"] == py_info
    same_md5 = js["hmd5"] == py_hmd5
    same_chk = js["chksum"] == py_chk
    ok_all &= same_info and same_md5 and same_chk
    print("case pw=%r info=%s md5=%s chksum=%s" % (obj["password"], same_info, same_md5, same_chk))
    if not same_info:
        print("  py:", py_info)
        print("  js:", js["info"])

print("ALL MATCH" if ok_all else "MISMATCH")
sys.exit(0 if ok_all else 1)

