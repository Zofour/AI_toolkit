"""配置加载：config.json，缺失则用默认值并生成随机 token。"""
from __future__ import annotations

import json
import os
import pathlib
import secrets

DEFAULTS = {
    # 监听地址：0.0.0.0 = 局域网 + Tailscale 都能访问（配合 token 鉴权）
    # 想更保守可改成 Tailscale 网卡 IP，例如 "100.x.y.z"
    "bind_host": "0.0.0.0",
    "port": 8787,
    # 手机端（WebSocket / REST / 配对）鉴权 token，首次运行自动生成
    "token": "",
    # 真上游的 OpenAI 兼容根地址（Chatbox 会经本服务转发到这里）
    # 例：https://api.deepseek.com/v1  https://api.openai.com/v1
    #    http://127.0.0.1:11434/v1 (Ollama)
    "upstream_base": "https://api.deepseek.com/v1",
    # 是否透传 Chatbox 带来的 Authorization（即用 Chatbox 里填的 key 调上游）
    "forward_authorization": True,
    # 兜底通知（App 不在线时）。topic 留空则关闭。可用自建 ntfy。
    "ntfy_url": "https://ntfy.sh",
    "ntfy_topic": "",
    # 每个会话在内存中保留的最大事件数（用于重连续传）
    "session_buffer_events": 3000,
    # 数据目录（会话事件持久化）
    "data_dir": "data",
    # 图片 blob 最多保留多少个（超出按时间清理最旧）
    "blob_max_files": 800,
    # 临时文件清理：blob 总大小上限(MB) / 最大保留天数 / 日志阈值 / 清理间隔(分钟)
    "blob_max_mb": 300,
    "blob_max_age_days": 7,
    "log_max_mb": 10,
    "log_max_age_days": 3,
    "cleanup_interval_minutes": 60,
    # 会话保留天数（超过则自动删除；0 = 永久保留）
    "session_max_age_days": 30,
    # 过滤“自动生成标题”之类的元请求（只转发不捕获，避免手机端出现垃圾会话）
    "ignore_meta_requests": True,
    # 调试：把请求/上游原文写日志（含隐私，默认关）
    "log_bodies": False,
}


class Config:
    def __init__(self, data: dict, path: pathlib.Path | None = None):
        self._data = data
        self.path = path

    def __getitem__(self, k):
        return self._data[k]

    def get(self, k, default=None):
        return self._data.get(k, default)

    @property
    def data(self) -> dict:
        return self._data

    def save(self):
        if self.path:
            self.path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def load_config(path: str | os.PathLike | None = None) -> Config:
    p = pathlib.Path(path) if path else pathlib.Path(__file__).resolve().parent.parent / "config.json"
    data = dict(DEFAULTS)
    if p.exists():
        try:
            data.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # 配置损坏时不要直接崩
            print(f"[config] 读取 {p} 失败，用默认值：{e}")
    changed = False
    if not data.get("token"):
        data["token"] = secrets.token_urlsafe(24)
        changed = True
    cfg = Config(data, p)
    if changed and p.exists():
        cfg.save()
    elif not p.exists():
        # 首次运行也落一份，便于用户编辑
        try:
            cfg.save()
        except Exception:
            pass
    return cfg
