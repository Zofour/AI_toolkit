"""手动执行一次临时文件清理并打印结果。

用法:  python cleanup.py
（中继服务运行时也会每 60 分钟自动清一次）
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from relay.config import load_config  # noqa: E402
from relay.cleanup import run_cleanup  # noqa: E402


def main():
    cfg = load_config()
    data = pathlib.Path(cfg["data_dir"])
    blob = data / "blobs"
    log = pathlib.Path(cfg.get("log_dir", "."))
    st = run_cleanup(data, blob, log, cfg)
    print(json.dumps(st, ensure_ascii=False, indent=2))
    print()
    print(f"清理完成：删除 {st['removed_files']} 个临时文件，释放 {st['freed_mb']} MB")
    print(f"  图片缓存：{st['blob_files']} 个 / {st['blob_mb']} MB（上限 {cfg.get('blob_max_files')} 个 / "
          f"{cfg.get('blob_max_mb')} MB / {cfg.get('blob_max_age_days')} 天）")
    print(f"  会话数据：{st['session_files']} 个 / {st['session_mb']} MB"
          f"（保留 {cfg.get('session_max_age_days')} 天；过期由运行中的中继自动删除；0=永久）")


if __name__ == "__main__":
    main()
