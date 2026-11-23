# Chatbox Bridge · 协议规格（SPEC)

> 版本 v1 ｜ 电脑端中继 ⇄ 安卓 App ｜ 传输：WebSocket（JSON 文本帧）

## 1. 总体架构

```
Chatbox 桌面版 ──(API Host 指向 127.0.0.1:8787/v1，方案A)──►  电脑端中继(pc-relay)
                                                                  │ ① OpenAI兼容反向代理 → 真上游，顺路解析 SSE
                                                                  │ ② WebSocket 推送中心
                                                                  │ ③ REST（首屏/历史/配对）
                                                                  │ ④ ntfy 兜底通知
                                                                  ▼
                                                         Tailscale(加密) / 局域网
                                                                  ▼
                                                          安卓 App (Kotlin+Compose)
```

- **监听点**：方案 A。Chatbox 里把某服务商的 `API Host` 改成 `http://127.0.0.1:8787/v1`，
  本中继把请求转发真上游，并把流式回复的**助手正文**实时推给手机。
- **零改 Chatbox 源码**，只改一个「API Host」字段。

## 2. 事件信封（所有推送统一）

```json
{ "v": 1, "type": "msg.delta", "ts": 1728800000000,
  "sessionId": "8e041b273e32d7f9", "messageId": "a1b2c3d4e5f6",
  "seq": 42, "data": { "text": "增量文本" } }
```

| 字段 | 说明 |
|---|---|
| `v` | 协议版本（当前 1） |
| `type` | 消息类型（命名空间化，见下表） |
| `ts` | 毫秒时间戳 |
| `sessionId` | 会话指纹（= sha1(model + system + 首条user)[:16]） |
| `messageId` | 本条消息 id（user/assistant 各自唯一） |
| `seq` | 会话内单调递增序号（用于断线续传/去重） |

## 3. 消息类型

| type | 方向 | 说明 |
|---|---|---|
| `hello` | S→C | 连接成功后：`{protocolVersion, serverId, features[], controlTypes[], sessions[]}` |
| `msg.user` | S→C | 从请求体抽到的用户提问 |
| `msg.begin` | S→C | 助手消息开始 |
| `msg.delta` | S→C | **助手正文增量**（边生成边看） |
| `msg.reason` | S→C | **思考过程增量**（`reasoning_content`/`reasoning`），手机显示为「已深度思考」 |
| `msg.tool` | S→C | **工具调用增量**：`{index, id, name, argsDelta}`，手机显示为「运行命令 · <name>」 |
| `msg.tool_result` | S→C | **工具执行结果**（来自后续请求 `role=tool` 的消息）：`{toolId, name, text}`，手机显示为「工具返回」 |
| `msg.image` | S→C | **图片**：`{blobId, mime, w, h}`；字节经 `GET /blobs/{blobId}` 按需拉取，手机上内联显示、点击放大 |
| `msg.done` | S→C | 助手消息完成：`{text, finishReason}`（同轮所有条目据此置为完成） |
| `pong` | S→C | 心跳应答 |
| `subscribed` | S→C | 订阅结果：`{sessionId, all, replayed}` |
| `session.deleted` | S→C | 某会话被删除（长按清除），客户端据此同步移除 |
| `error` | S→C | 协议/解析错误 |
| `ping` | C→S | 心跳 |
| `subscribe` | C→S | `{sessionId?, sinceSeq?}`：`sessionId` 省略=订阅全部；给 `sinceSeq` 才回放历史 |
| `control.*` | C→S | **回控（预留）** 见第 5 节 |
| `control.result` | S→C | **回控结果（预留）** |

`hello.features`：`["sessions","resume","markdown","notify","control.reserved"]`

## 4. REST 接口

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| POST | `/v1/chat/completions` | 仅本机(loopback) | 反向代理 + 捕获（Chatbox 用） |
| ANY | `/v1/*` | 仅本机 | 其余透传（如 `/v1/models`） |
| GET | `/health` | 无 | 健康检查 |
| GET | `/sessions?token=` | token | 会话列表 |
| GET | `/sessions/{id}/messages?since=&limit=&token=` | token | 历史事件 |
| DELETE | `/sessions/{id}?token=` | token | 删除会话（内存+文件），并广播 `session.deleted` |
| GET | `/blobs/{name}?token=` | token | 取图片二进制（手机内联显示用） |
| POST | `/cleanup?token=` | token | 立即执行一次临时文件清理，返回统计 |
| GET | `/pair` | 仅本机 | 配对页（token + ws 地址 + 二维码） |
| WS | `/ws?token=` | token | 实时推送 |

> 鉴权：`Authorization: Bearer <token>` 或 `?token=<token>`；`/v1/*` 只允许回环地址（Chatbox 本机），
> 手机侧一律走 token 保护的 `/ws`、`/sessions`。

## 5. 回控（已实现）

手机发消息 → 中继 → 电脑上的**注入器** → 打进 Chatbox 输入框并发送 →
Chatbox 正常生成回复（并以用户气泡显示在 Chatbox 里）→ 中继通过代理捕获 → 推回手机。

| type | 方向 | 说明 |
|---|---|---|
| `control.send` | C→S | 手机发消息：`{text, reqId}` |
| `control.dispatch` | S→C | 中继下发给注入器：`{text, reqId}` |
| `control.result` | S→C | 结果：`{ok, mode:"inject", reqId, error}`（`error=no_injector` 表示电脑未运行注入器） |
| `injector.register` | C→S | 注入器上线登记（中继另广播 `bridge.status{canControl}`） |
| `injector.report` | C→S | 注入器上报 DOM 自动化结果 `{reqId, ok, stage}` |
| `control.new` | C→S | 手机请求在 Chatbox **新建一个会话**（点「新对话」，模型默认「转发手机 · DeepSeek V4.1 Flash」）；结果回 `control.result{mode:"new"}` |

注入实现（`chatbox_inject.py`）：连中继 WS + 连 Chatbox 的 CDP（`--remote-debugging-port=9333`），
收到 `control.dispatch` 后：聚焦输入框 → `Input.insertText`（真实打字，React 可感知）→ 点击 `aria-label="发送"`。

> 一键启动：`pc-relay/start_bridge.bat`（已放到**桌面**和**启动**文件夹，开机自动运行：
> 自动确保 Chatbox 带调试端口 → 起中继 → 起注入器）。它会重启一次 Chatbox 以开调试端口。

### 精确路由到对应会话（已实现）

中继捕获到某会话的新用户消息时，会向注入器发 `bridge.capture`；注入器随即读取 Chatbox
「当前活动会话」的 `data-session-id`（侧栏 `[data-testid="session-item"]` 且 class 含
`brand-secondary` 者为活动项），建立 **中继会话 ↔ Chatbox 会话** 映射并回传
`injector.map`；中继据此把会话标题更新为 Chatbox 的标题（手机端与桌面端显示一致）。

手机发消息时带 `sessionId` → 中继在 `control.dispatch` 里附上 `chatboxId`/`title` →
注入器**先点选对应会话**（`[data-session-id="..."]`.click）再打字发送，
保证“在哪个对话发，就落到哪个 Chatbox 对话”。映射持久化在 `pc-relay/_cb_map.json`，
未命中映射时依次回退到「按标题找」「当前会话」。
> 注：消息会进入 Chatbox **当前打开的会话**；手机端若要同步看到，该会话的模型须指向本中继。

### 过滤“自动生成标题”元请求

Chatbox 会自动为新对话生成标题，它会向模型发一个 `messages==1`、无 `tools`、
user 以 `Based on the chat history, give this conversation …` 开头的**元请求**。
中继对这种请求**只转发、不捕获**（不建会话、不推手机），避免手机端出现垃圾会话。
开关：`config.json` 的 `ignore_meta_requests`（默认 `true`）。

其余控制类型（`control.stop` / `control.session.switch` / `control.model.switch`）仍保留未实现。

### 图片（Chatbox → 手机，已实现）

中继从**请求体**里抽取图片（不依赖注入器/CDP，也不用改 Chatbox）：
- 用户附件：`content:[{type:"image_url", image_url:{url}}]`（通常是 data URL）；
- 正文里的 Markdown 图片 `![](...)`：支持 `data:` / `http(s)://` / **本地文件路径**（中继直接读盘）。

抽取后按内容 sha1 去重存为 blob（超过 2.5MB 自动压到长边 2000px），推送 `msg.image`（只带引用，不走 WebSocket 传字节）；手机用 `GET /blobs/{id}?token=` 拉取内联渲染（Coil）。
blob 缓存在 `pc-relay/data/blobs/`，超过 `blob_max_files`（默认 800）按时间清理。

### 临时文件自动清理

中继启动时 + 每 `cleanup_interval_minutes`（默认 60）分钟自动跑一次（`relay/cleanup.py`）：
- blob：超 `blob_max_age_days`(7) → 删；超 `blob_max_files`(800) → 删最旧；超 `blob_max_mb`(300) → 删最旧；
- 日志：`*.log`/`*.err` 超 `log_max_age_days`(3) 或 `log_max_mb`(10) → 删；
- **会话过期**：最后更新时间超 `session_max_age_days`(30) 的会话 → 删文件+内存，并广播 `session.deleted`（`0` = 永久保留）；
- `stat_sessions` 提供当前会话数量/体积统计。
手动：`python cleanup.py` / `cleanup_once.bat` / `POST /cleanup`。

### 对 Chatbox UI 版本敏感的选择器（已适配 1.24.1）

| 用途 | 选择器 | 1.24.1 实际值 |
|---|---|---|
| 输入框 | `textarea[placeholder*="输入"]` | 「输入消息，Enter 加入队列」 |
| 发送 | `button[aria-label*="发送"]` | 空闲为「发送」；**生成中会变成「停止」，此时无法注入** |
| 新对话 | `button` 文本以「新对话」开头 | 「新对话 Ctrl+N」 |
| 会话项 | `[data-testid="session-item"]` + `data-session-id` | 未变 |
| 活动会话 | class 含 `bg-chatbox-background-secondary-hover` | 旧版为 `…brand-secondary` |

> Chatbox 升级后若回控失效，优先重新核对上表（用 CDP 查看 DOM）。

## 6. 为"加功能"预留的扩展点

1. `hello.features / controlTypes`：能力协商，新功能不破坏旧客户端（按能力开 UI）。
2. 命名空间化 type：新增功能=新增一个 type（如 `file.transfer`、`notify.push`），主结构不变。
3. `seq` + `subscribe(sinceSeq)`：任何新事件天然支持断线续传。
4. 会话指纹函数独立（`relay/store.py: session_key`）：换分组策略不改其它代码。

## 7. 安全

- **网络**：Tailscale（WireGuard 端到端加密 + 设备鉴权），中继不暴露公网端口。
- **应用**：所有手机端接口校验 token；WS 握手 token 错直接关闭（code 4401）。
- **配对**：电脑端生成随机 token（`config.json`），`/pair` 页展示，手机扫码/粘贴录入。
- **代理**：`/v1/*` 仅回环，防止被远端滥用。
