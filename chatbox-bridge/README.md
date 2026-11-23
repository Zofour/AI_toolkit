# Chatbox Bridge ⌁ 手机实时看电脑上的 Chatbox 回复

把电脑上 Chatbox 正在生成的回复，**实时（逐字）**推到安卓手机，出门在外也能看（Tailscale）。零改 Chatbox 源码。

```
电脑                              Tailscale（加密）              手机
Chatbox ──API Host──► pc-relay ─────────────► ChatboxBridge App
                        (WebSocket)              (前台服务常驻)
```

## 目录

```
chatbox-bridge/
├─ pc-relay/            电脑端中继（Python）
│   ├─ run.bat          双击启动
│   ├─ run.py           python run.py
│   ├─ config.json      上游地址 / 端口 / token（首启自动生成）
│   ├─ relay/           源码
│   └─ tests/test_e2e.py 端到端自测
├─ android/             安卓工程（Gradle）
│   ├─ build_apk.bat    双击出 APK
│   └─ app/build/outputs/apk/debug/app-debug.apk
├─ tools/jdk17/         便携 JDK17（构建用）
├─ ChatboxBridge-debug.apk   ← 已构建好的安装包
└─ SPEC.md              协议规格
```

## 快速开始

### 一、电脑端
1. 编辑 `pc-relay/config.json`，把 `upstream_base` 改成你 Chatbox 里用的服务商根地址，
   例如 `https://api.deepseek.com/v1` 或 `https://api.openai.com/v1`。
2. 双击 `pc-relay/run.bat`（或 `python run.py`）。控制台会打印 **Token**、**Chatbox API Host**、**手机可连地址**。
3. 在 Chatbox 新建/编辑一个「自定义服务商」：
   - **API Host** 填 `http://127.0.0.1:8787/v1`
   - **API Key** 填**真上游的 key**（会透传给上游）
4. 用这个服务商随便聊一句，末尾会看到回复实时推送到手机。

### 二、手机端
1. 装 `ChatboxBridge-debug.apk`。
2. 电脑浏览器打开 `http://127.0.0.1:8787/pair` 查看地址与 Token（或扫码）。
3. App 里填 WebSocket 地址 + Token，点「保存并连接」。
   - 在家：`ws://192.168.x.x:8787/ws`
   - 出门：`ws://100.x.y.z:8787/ws`（Tailscale）

### 三、出门可用（Tailscale）
1. 电脑与手机各装 [Tailscale](https://tailscale.com)，登录同一账号。
2. 用电脑的 `100.x.y.z` 地址填到 App 即可（在家/出门同一个地址，无需切换）。
3. 手机端把 App 加入**电池优化白名单**，保证后台不被杀。

## 重新构建 APK
双击 `android/build_apk.bat`（首次构建约 2 分钟，需联网下依赖）。
产物：`android/app/build/outputs/apk/debug/app-debug.apk`。

## 自测
```
cd pc-relay && python tests/test_e2e.py
```
覆盖：hello / 用户消息 / 增量 / 完成 / 回控预留 / REST / 续传 / 鉴权。

## 回控（手机发消息，显示在电脑 Chatbox 里）

想要手机也能发消息，电脑端改用 **`pc-relay/start_bridge.bat`** 启动（一键：确保 Chatbox 带调试端口 → 起中继 → 起注入器）：

1. 双击 `pc-relay/start_bridge.bat`（会重启一次 Chatbox 以开启调试端口，并弹出两个窗口，保持开着）。
2. 手机上打开会话，底部输入框即可发消息。
3. 手机发的消息会像你亲手输入一样**出现在电脑 Chatbox 里**（用户气泡），并由 Chatbox 正常生成回复；
   **且在哪个对话发，就会落到对应的 Chatbox 对话里**（自动切换 Chatbox 会话）。
4. 点右上角 **＋** 可**新建会话**：会在 Chatbox 里新建一个对话（模型默认「转发手机 · DeepSeek V4.1 Flash」）；
   你在手机上发第一条消息后，它就会同时出现在电脑和手机的会话列表里。

> 原理：中继把你的消息交给“注入器”，注入器用 Chrome DevTools 协议控制 Chatbox 的输入框并点发送。
> 手机端要同步看到这条消息与回复，该会话的模型需指向本中继（即 Chatbox 里的自定义服务商 API Host = `http://127.0.0.1:8787/v1`）。

## 临时文件清理

- 中继运行时**每 60 分钟自动清理**一次，启动时也会先清一次。
- 清理对象：**图片 blob 缓存**（超 7 天 / 超 800 个 / 超 300MB 就删最旧）+ **日志**（`*.log`/`*.err` 超 3 天或超 10MB）。
- **会话只保留 30 天**：最后更新时间超过 30 天的会话会被自动删除（文件+内存），并广播给手机同步移除。改天数：`config.json` 的 `session_max_age_days`（`0` = 永久保留）。
- 手动清一次：双击 `pc-relay\cleanup_once.bat`（或 `python cleanup.py`）。
- 调参数：`config.json` 里的 `blob_max_files / blob_max_mb / blob_max_age_days / log_max_mb / log_max_age_days / cleanup_interval_minutes / session_max_age_days`。
- 运行时可在 `GET /health` 的 `cleanup` 字段看到当前占用。

## 功能状态
- ✅ 实时逐字推送、会话列表、历史回放、断线续传、前台常驻、本地通知、ntfy 兜底（可配）
- ✅ 工作流时间线（思考/工具调用/工具结果）、消息收缩展开、长按清除会话
- ✅ **图片（Chatbox → 手机）**：对话里的图片（附件 / 正文 Markdown 图 / 本地图片路径）在手机上内联显示、点击放大
- ✅ **回控**：手机发消息 → 自动切到对应会话并注入 Chatbox 发送（显示在 Chatbox 内）
- ✅ **手机新建会话**：在 Chatbox 新建对话（默认模型「转发手机 · DeepSeek V4.1 Flash」）
- 🔒 其余控制（停止/切会话/切模型）仍预留未实现
