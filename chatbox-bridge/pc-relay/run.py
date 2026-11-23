"""启动电脑端中继服务。

用法：
    python run.py                # 用 pc-relay/config.json（首次自动生成）
    python run.py --port 8787
    python run.py --host 100.x.y.z   # 只绑 Tailscale 网卡

启动后：Chatbox 的某个服务商「API Host」填 http://127.0.0.1:<port>/v1，
手机端扫 http://127.0.0.1:<port>/pair 里的二维码即可。
"""
from __future__ import annotations

import argparse

import uvicorn

from relay.app import create_app, _lan_ips
from relay.config import load_config


def main():
    ap = argparse.ArgumentParser(description="Chatbox Bridge 电脑端中继")
    ap.add_argument("--config", default=None, help="配置文件路径")
    ap.add_argument("--host", default=None, help="监听地址（覆盖 config）")
    ap.add_argument("--port", type=int, default=None, help="监听端口（覆盖 config）")
    ap.add_argument("--reload", action="store_true", help="开发用热重载")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.host:
        cfg.data["bind_host"] = args.host
    if args.port:
        cfg.data["port"] = args.port

    app = create_app(cfg)

    port = cfg["port"]
    print("=" * 68)
    print("  Chatbox Bridge · 电脑端中继")
    print("=" * 68)
    print(f"  上游(上游真地址) : {cfg['upstream_base']}")
    print(f"  监听             : {cfg['bind_host']}:{port}")
    print(f"  Token            : {cfg['token']}")
    print(f"  Chatbox API Host : http://127.0.0.1:{port}/v1")
    print(f"  手机端配对页     : http://127.0.0.1:{port}/pair")
    for ip in _lan_ips():
        tag = "  <- 出门在外用这个(Tailscale)" if ip.startswith("100.") else ""
        print(f"  手机可连地址     : ws://{ip}:{port}/ws{tag}")
    if not cfg["upstream_base"]:
        print("  !! 尚未设置 upstream_base（config.json）")
    print("=" * 68)

    uvicorn.run(
        app,
        host=cfg["bind_host"],
        port=port,
        log_level="info",
        ws_ping_interval=25,
        ws_ping_timeout=60,
    )


if __name__ == "__main__":
    main()
