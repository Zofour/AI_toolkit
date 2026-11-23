# AI Gen Studio

本地「文本模型（Ollama）+ 生图模型（ComfyUI）」一体化生图应用。

## 启动
1. 确认 **ComfyUI Desktop** 在跑（`http://127.0.0.1:8000`）
2. 确认 **Ollama** 在跑（`http://127.0.0.1:11434`）
3. 双击 `run.bat`（本地）或桌面上的 **`AI Gen Studio 远程.bat`**（手机远程），浏览器打开 `http://127.0.0.1:5000`

> **新增模型后怎么办？** 启动时程序会自动扫一遍模型列表（控制台会打印）；页面里也有 **🔄 刷新模型** 按钮；从别的窗口切回浏览器时会自动重扫。API 响应已禁用缓存，不会再看到旧列表。

## 手机远程（Tailscale + APK）

**电脑端**：双击桌面 `AI Gen Studio 远程.bat`
- 只绑定 Tailscale 地址（自动 `tailscale ip -4` 探测），端口 **8848**，**不暴露给局域网**
- 控制台会打印手机要填的地址，例如 `http://100.64.0.1:8848`
- 本地浏览器访问 127.0.0.1:8848 是**连不上**的（故意的）；本地用 `run.bat` 的 5000
- 想改成“绑全网卡+只放行 Tailscale 网段”（方案1+，本地方便），改 `app.py` 的 `--remote` 分支即可

**手机端**：`AI Gen Studio 手机版.apk`
- 首次打开填电脑打印的地址（已预填默认值），掉一次「保存并连接」
- 菜单（右上角 ⚙）里可改地址 / 清缓存重载 / 返回上一页
- 功能与电脑端一致：选模型、写需求、生成提示词、生图、看图、模式2
- **📲 存到手机** / **📲 存整批** → 存到手机 **`相册/Pictures/电脑/`**（Android 10+ 不需要任何存储权限）
- 图生图：可 **选手机相册的图** 或 **拍照** 当输入图
- 重新编译：`cd android` 后
  ```
  set JAVA_HOME=C:\chatbox_temp\jdk17\jdk-17.0.20.1+1
  set ANDROID_HOME=C:\Users\yourname\AppData\Local\Android\Sdk
  %USERPROFILE%\.gradle\wrapper\dists\gradle-8.13-bin\5xuhj0ry160q40clulazy9h7d\gradle-8.13\bin\gradle.bat assembleDebug
  ```


## 两个模式
- **模式1**：文本模型把中文需求转成多条**英文**提示词 → 你点选/勾选 → 生图。
- **模式2**：只有**识图模型**能选（`qwen35-zh` / `qwen3.5-abliterated-truthful` / `qwen3-vl:8b` / `gemma3:12b`）。
  全自动：生图 → 逐张交给识图模型判断 → 不达标就自动改写提示词再生成，最多 **16 轮**；达标自动保存。

## 关键设定
- **候选提示词**：条数 1–10，可单选/多选；多选「批量生图」时**严格串行**（一条一条来，避免显存爆）。
- **提示词风格**（三档，默认标签式）：`标签式` 输出逗号分隔的英文标签（如 `1girl, solo, silver hair, neon lights, masterpiece`）；`描述句` 输出完整自然语言句子；`跟随模型` 自动按生图模型类型选（SD 系→标签式，Z-Image/anima→描述句）。
- **一次张数**：1–16（同一提示词一次出 N 张）。
- **图生图**：切到「图生图」才出现输入图预览；宽高自动采用输入图尺寸；denoise 可调。
- **模型分两类**：标准模型（SD/SDXL，走 CheckpointLoader）与大模型（Z-Image Turbo / Anima，走 UNETLoader），各自用对应官方工作流。
- **分辨率智能默认**：模型文件 >6GB 视为 SDXL → 1024；Z-Image/Anima → 1024；其余 512。
- **temp 目录**（默认 `D:\image_temp`）：**所有**生成的图片（无论达标与否）都会自动落盘，**本程序永不删除**，只能你自己删。
- **正式保存目录**：设置一次记住，「保存」按钮与模式2 达标图都写到这里。
- **文件命名**（temp 与正式保存统一）：`生图模型名+提示词前60字+时间戳_序号.png`
  例：`NetaYumev35_pretrained_all_in_one+1girl, umbrella, rainy neon street+20261016_170500_03.png`
  非法字符 `\ / : * ? " < > |` 自动换成 `_`，模型名截 40 字 / 提示词截 60 字 / 整名上限 150 字。
- **历史记录**：`history.json`（含每轮的提示词、参数、图片路径）。
- 模式1/模式2 都不限制思考模型的思考长度。

## 目录
```
app.py             Flask 后端（API / SSE 进度 / 归档 / 历史）
comfy.py           ComfyUI 客户端 + 三类工作流构建器
ollama_client.py   Ollama 客户端（能力探测 / 提示词生成 / 图像评判）
config.json        设置（首次运行自动生成）
history.json       历史记录
static/            前端（index.html / app.js / style.css）
run.bat            启动脚本
```
