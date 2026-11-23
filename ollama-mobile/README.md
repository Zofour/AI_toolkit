# Ollama 口袋 (Ollama Mobile)

手机端 Ollama 客户端：通过 **Tailscale** 在任意网络下连接电脑上的 Ollama，支持选模型、切换模型自动卸载、多会话管理。

- 包名：`com.ollama.mobile`
- 工程：`C:\chatbox_temp\ollama-mobile\android`（Kotlin + Jetpack Compose，AGP 8.9.1 / Kotlin 2.0.21 / compileSdk 36 / minSdk 26）
- 产物：`app\build\outputs\apk\debug\app-debug.apk`

## 一、电脑端准备

1. 让 Ollama 监听所有网卡（默认 Windows 版已监听 `::`，若只监听 127.0.0.1 需设置环境变量）：

   ```powershell
   setx OLLAMA_HOST 0.0.0.0:11434
   ```
   设置后重启 Ollama。

2. 放行防火墙 11434（本机已存在规则 `ALLOW OLLAMA PORT 11434`，重装系统后需重建）：

   ```powershell
   netsh advfirewall firewall add rule name="Ollama 11434" dir=in action=allow protocol=TCP localport=11434
   ```

3. 查看本机 Tailscale IP（App 默认填的就是这个）：

   ```powershell
   tailscale ip -4
   ```

4. 手机与电脑登录**同一个 Tailscale 账号**，并在手机端打开 Tailscale 开关。

## 二、手机端使用

| 操作 | 位置 |
|---|---|
| 选择 / 切换模型 | 顶栏模型名或右上角芯片图标，下拉列表显示参数量、体积、是否支持「视觉」、是否已驻留显存 |
| 发图片 | 输入框左边的图片按钮 → 系统相册选图（最多 4 张），可点缩略图右上角 ✕ 移除 |
| 新建对话 | 顶栏 `+` |
| 切换 / 删除对话 | 左上角抽屉，每个对话独立保存自己的模型和上下文 |
| 停止生成 | 生成中右下角按钮变红色 ✕ |
| 复制消息 | 长按气泡 |
| 看思考过程 | deepseek-r1 / qwen3 等思考模型的灰色「思考过程」可点开 |
| 修改服务器地址 | 抽屉 → 设置 |
| 手动释放显存 | 抽屉 → 卸载模型 |

## 二·五、图片（视觉）功能说明

- 选图后本地会**纠正 EXIF 方向 → 最长边缩到 1280px → 压成 JPEG(85)**，再转裸 base64 传给 Ollama 的 `images` 字段。原图 12MP 一般会压到 150～300 KB，Tailscale 上传无压力。
- 只有带 `vision` 能力的模型能吃图（本机实测：`qwen3-vl:8b`、`gemma3:12b`）。下拉菜单里这些模型会标「视觉」；当前模型不支持时发图会被拦下并提示换模型。
- **图片只随「本次提问」上传**，历史轮次只保留文字，避免每轮都把几 MB 图片重传一遍（副作用：隔轮追问时模型看不到早先的图）。
- 图片存在 App 私有目录 `filesDir/images/`，气泡里直接从本地文件解码显示；删会话不会删图片文件（目前不做清理）。


**地址策略**：主地址填电脑的 Tailscale IP（`http://100.64.0.1:11434`），备用地址填家里局域网 IP（`http://192.168.1.100:11434`）。启动时先试主地址，失败自动退回备用地址——这样在外用 Tailscale、在家用 Wi-Fi 都不用手动改。

## 三、切换模型时的显存释放（关键行为）

`POST /api/generate {"model": "<旧模型>", "keep_alive": 0}` → Ollama 立即卸载该模型。

具体实现（`AppViewModel.selectModel()`）：
1. 先把会话的模型改成新的；
2. 卸载上一个模型；
3. 再查 `/api/ps`，把所有仍驻留、且不是新模型的模型一并卸载；
4. 每次发消息前也执行一次同样的清理（`ensureOnly()`），保证显存里最多只有一个模型。

实测：`minicpm5-2b` 驻留中 → 切到 `gemma3:12b` → `/api/ps` 立即变空。

## 四、重新构建

双击 `build_apk.bat`，或：

```powershell
powershell -File C:\chatbox_temp\ai_toolkit\apk_build.ps1 -Project C:\chatbox_temp\ollama-mobile\android -NoDaemon
adb install -r C:\chatbox_temp\ollama-mobile\android\app\build\outputs\apk\debug\app-debug.apk
```

> 注意：gradle 必须 `-NoDaemon`（否则工具调用会被 daemon 挂死）；JDK 必须用 `C:\chatbox_temp\chatbox-bridge\tools\jdk17`，不能用 PATH 上的 Oracle JRE 8。

## 五、代码结构

```
app/src/main/java/com/ollama/mobile/
├── MainActivity.kt    入口（Compose）
├── Models.kt          数据类：OllamaModel / ChatMessage / Conversation / UiState
├── OllamaClient.kt    HTTP：/api/version /api/tags /api/ps /api/generate(unload) /api/chat(流式)
├── AppViewModel.kt    状态机：会话、模型切换+卸载、流式接收、本地持久化
├── Store.kt           会话 JSON 落盘（filesDir/conversations.json）
├── Settings.kt        SharedPreferences：地址/备用地址/keep_alive/系统提示词
└── Ui.kt              Compose UI：抽屉、模型下拉、气泡、代码块、设置
```

## 六、已知限制

- 图片上传只支持「当轮」，隔轮追问看不到早先的图片（为省流量有意为之）。
- 会话保存在 App 私有目录，清除数据即丢失；没有云同步。
- 历史消息全量重发给 Ollama（无自动上下文裁剪），超长对话可能超出模型 `num_ctx`。
- APK 为 debug 签名，仅自用；要给他人安装需自行加 release 签名配置。
