import os, subprocess, sys, time, json

URL = "https://download.openstreetmap.fr/extracts/asia/china/beijing-latest.osm.pbf"
TOTAL = 39_800_000  # 实际以 HEAD 为准
N = int(sys.argv[2]) if len(sys.argv) > 2 else 16
base = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(base, "beijing.osm.pbf")
cdir = os.path.join(base, "chunks")
os.makedirs(cdir, exist_ok=True)
budget = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0

def sh(path):
    return os.path.getsize(path) if os.path.exists(path) else 0

# 用 HEAD 拿真实长度
import urllib.request
req = urllib.request.Request(URL, method="HEAD")
with urllib.request.urlopen(req, timeout=20) as r:
    TOTAL = int(r.headers["Content-Length"])
chunk = TOTAL // N + 1

deadline = time.time() + budget
rounds = 0
while time.time() < deadline:
    rounds += 1
    procs = []
    for i in range(N):
        a = i * chunk
        b = min(a + chunk - 1, TOTAL - 1)
        f = os.path.join(cdir, f"c{i}.bin")
        need = b - a + 1 - sh(f)
        if need <= 0:
            continue
        already = sh(f)
        p = subprocess.Popen(["curl.exe", "-s", "-L", "--max-time", f"{max(5, deadline-time.time()):.0f}",
                              "-r", f"{a+already}-{b}", URL],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        procs.append((p, f))
    for p, f in procs:
        data, _ = p.communicate()
        if data:
            with open(f, "ab") as fh:
                fh.write(data)
    done = sum(sh(os.path.join(cdir, f"c{i}.bin")) for i in range(N))
    print(f"round {rounds}: {done/1e6:.2f}/{TOTAL/1e6:.2f} MB ({done*100//TOTAL}%)", flush=True)
    if done >= TOTAL:
        break

done = sum(sh(os.path.join(cdir, f"c{i}.bin")) for i in range(N))
if done >= TOTAL:
    with open(out, "wb") as w:
        for i in range(N):
            with open(os.path.join(cdir, f"c{i}.bin"), "rb") as r:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    w.write(b)
    print("ASSEMBLED", os.path.getsize(out), "bytes ->", out)
else:
    print(f"INCOMPLETE {done}/{TOTAL}")
