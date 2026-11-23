# 本机工作流备份

一套在 Windows 11 单机上长期打磨出来的「个人 AI / 自动化工作流」源码备份。
所有脚本都在真机跑通过，附带踩坑记录。详见 [DESENSITIZE.md](DESENSITIZE.md)。

- 宿主环境：Windows 11（PowerShell 5.1 为主）、Python 3.13、Node 20、JDK 17、Android SDK 36
- 显卡：NVIDIA RTX 5080 Laptop 16 GB（脚本里的显存/速度数据都基于这张卡）
- 习惯：能脚本化的一律脚本化，重复任务先查脚本索引 `ai_toolkit/INDEX.md`

## 目录结构

| 目录 | 是什么 | 入口 |
|---|---|---|
| `ai_toolkit/` | 通用工具箱：环境自检、Word 公式、Markdown→Word、TTS、频谱图、视频补帧、HF 下载、APK 构建、GUI 操控、离线 OSM 路线 | `INDEX.md`（一页纸索引，先看这个） |
| `k230-style-pipeline/` | K230 开发板「人物风格化 → kmodel」四步流水线（LoRA 训练 / 批量生图 / 蒸馏学生网 / nncase 编译）+ 板端实时风格化脚本 | `1.训练Lora.bat` … `4.生成kmodl文件.bat` |
| `chatbox-bridge/` | 把电脑上 Chatbox 的流式回复实时推到手机：Python 中继 + Kotlin App | `pc-relay/run.bat`、`android/build_apk.bat` |
| `filehub/` | 手机只读访问电脑图片/视频：Python 标准库 HTTP 服务 + Compose App（缩略图、Range 播放、全盘/U 盘共享） | `server/run.bat`、`build_apk.bat` |
| `paper-scan/` | 文档扫描 App：拍照 → 自动裁纸/透视矫正/去阴影/纸面变白 → PDF/ZIP → 分享微信 | `build_apk.bat` |
| `wifi_auto_login/` | 校园网（srun 认证）自动登录：Python 守护 + 安卓前台服务版 APK | `srun_autologin.py`、`android/` |
| `thinking-translator/` | 把模型返回的英文 `reasoning_content` 实时翻成中文的 OpenAI 兼容反向代理 | `run_proxy.bat` |
| `ai-gen-studio/` | 本地网页工作台：Ollama 写提示词 + ComfyUI 出图，含自动质检重试 | `run.bat` |
| `prompt-studio/` | 提示词批量出图工作台（Tkinter GUI，显存互斥、LoRA 挂载、批量） | `run.bat` |
| `ollama-mobile/` | 手机端 Ollama 客户端（Compose，切模型即释放显存） | `build_apk.bat` |
| `game-localize/` | Unity 游戏离线汉化服务（XUnity.AutoTranslator 的 CustomTranslate 后端，纯本地模型） | `srv.py` |
| `deepseek-demo/` | DeepSeek 官方开源前端的安卓 WebView 壳（离线打包、麦克风、文件下载桥） | `android-app/build_apk.bat` |

## 通用约定

1. **占位符**
   - `C:\Users\yourname` = 你的家目录（原文件里是真实用户名）
   - `100.64.0.1` / `192.168.1.100` / `10.0.0.1` = 原内网/Tailscale 地址
   - `CHANGE_ME` = 令牌、密码；`sk-YOUR_API_KEY` = 大模型 API Key
   - `2025000000` = 校园网账号（学号）
2. **配置文件**：所有 `config.json` 都以 `config.example.json` 形式提供，
   复制改名后填入自己的值即可：`copy config.example.json config.json`
3. **硬编码路径**：部分脚本写了绝对路径（ComfyUI 目录、输出目录等），
   首次使用请全局搜索 `yourname` 和 `D:\\`、`D:/` 改成你本机的路径。
4. **构建安卓 App**：统一走 `powershell -File ai_toolkit\apk_build.ps1 -Project <工程根> -Variant debug -NoDaemon`
   （脚本自动挑 JDK17、设 SDK、找 gradle；`-Probe` 可先探测环境）

## 依赖一览

- Python：`python-docx openpyxl PyMuPDF pandas matplotlib numpy opencv-python pillow requests
  websocket-client flask fastapi uvicorn httpx websockets edge-tts yt-dlp osmium networkx
  PyQt5 pywin32 lxml`（按需安装，`ai_toolkit/probe_env.py` 可一次性自检）
- 外部程序：ffmpeg（含 NVENC）、Ollama、ComfyUI、nncase（WSL 内）、RIFE ncnn-vulkan
- 安卓：JDK 17 + Android SDK（platform 36）+ Gradle 8.13
- 前端（`deepseek-demo/`）：Node + `npx rspack build`

## 未收录的内容

体积大或不适合公开的资产**不在本仓库**：模型权重（gguf/onnx/ckpt/safetensors）、
数据集、构建产物（build/、node_modules/、dist/、APK）、日志、截图、
第三方二进制（RIFE、JDK、SDK）、游戏剧本文本、B 站登录态、以及含真实账号的 `config.json`。
需要时按各目录 README 自行下载/生成。

## 免责与合规

- `ai_toolkit/win_gui.py` 能真实操控桌面 GUI（含微信）。微信官方禁止自动化，
  批量发消息/加好友有封号风险，只做自己明确需要的单次操作。
- `wifi_auto_login/` 用于自己账号的自动认证，请遵守学校网络使用规定。
- `ai_toolkit/bili_interp.py` 下载视频需要登录态（SESSDATA），请只处理自己有权使用的内容。
- `game-localize/` 只提供工具链，不附带任何游戏资源或剧本。

## 许可

代码本身可自由使用/修改（建议你自己补一个 LICENSE，如 MIT）。
各安卓工程内若保留了第三方库的 LICENSE 文件，以那些为准；
`deepseek-demo/` 的前端来自 `deepseek-ai/chat-demo`（MIT）。
