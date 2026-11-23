# Thinking Translator · 把 AI 的「思考过程」自动翻译成中文

一个 **本机运行的 OpenAI 兼容反向代理**：把上游大模型返回的
`reasoning_content`（思考过程，通常为英文）**逐句实时翻译成简体中文**，
再流式回给 Chatbox 显示；正文答案默认原样透传。

```
Chatbox ──► 本机代理(127.0.0.1:8788) ──► 真正的模型服务商
                    │
         把 reasoning 逐句翻译成中文后回传 ◄── 本地翻译引擎
```

## 为什么能自动

Chatbox 支持「自定义 OpenAI 兼容服务商」。把它的 API Host 指向本代理即可，
**不用改 Chatbox 本身**。代理拦截 SSE 流、只翻译思考字段。

---

## 快速开始

### 1) 选一个翻译引擎

**A. 本机 Ollama（推荐，质量最好）** —— 你机器上已经装了 Ollama：
```
translator engine = Ollama，模型建议 gemma3:12b / qwen3-vl:8b / deepseek-r1:14b
```

**B. 自带的 Qwen2.5-1.5B（离线、省显存、无需 Ollama）**
模型已下载到 `models/Qwen2.5-1.5B-Instruct`（约 3GB）。

### 2) 启动代理

双击 `run_proxy.bat`，或命令行：

```powershell
# 用 Ollama 当翻译引擎
$env:UPSTREAM_BASE   = "https://api.deepseek.com/v1"     # 你的真实服务商 base
$env:TRANSLATOR_BACKEND = "openai"
$env:TRANSLATOR_API_MODEL = "gemma3:12b"
python proxy.py
```
```powershell
# 用自带 Qwen 当翻译引擎
$env:UPSTREAM_BASE = "https://api.deepseek.com/v1"
$env:TRANSLATOR_BACKEND = "local"
python proxy.py
```

### 3) 在 Chatbox 里挂上

设置 → 模型提供方 → 添加**自定义提供方**（OpenAI API 兼容）：

| 字段 | 填 |
|---|---|
| API Host | `http://127.0.0.1:8788/v1` |
| API Key | 填你**真实上游**的 key（代理会原样转发） |
| 模型 | 填你在该上游要用的模型名，如 `deepseek-reasoner` |

之后用它对话，思考过程就是中文了。

---

## 文件

| 文件 | 作用 |
|---|---|
| `proxy.py` | 主程序：OpenAI 兼容反向代理 + 流式翻译 |
| `translator.py` | 翻译引擎（本地 Qwen / Ollama 两种），含代码块保护 |
| `run_proxy.bat` | 一键启动（改里面三行即可） |
| `cli.py` | 离线测试：`python cli.py "英文"` |
| `download_model.py` | 从 ModelScope 下载模型 |
| `mock_upstream.py` | 假上游，供本地测试 |
| `test_e2e.py` | 端到端自测：`python test_e2e.py [--fake]` |

## 可调环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `UPSTREAM_BASE` | 空（必填） | 真实服务商 base，含 `/v1` |
| `PORT` | 8788 | 本地监听端口 |
| `TRANSLATOR_BACKEND` | local | `local` 或 `openai` |
| `TRANSLATOR_API_BASE` | `http://127.0.0.1:11434/v1` | Ollama/LM Studio 地址 |
| `TRANSLATOR_API_MODEL` | `qwen3-vl:8b` | 翻译用模型 |
| `TRANSLATE_CONTENT` | 0 | 置 1 时连正文答案也翻译 |
| `MODEL_DIR` | `models/Qwen2.5-1.5B-Instruct` | 本地翻译模型目录 |
| `DEBUG` | 0 | 置 1 打印转发日志 |

## 已做的保护

- **代码块 ``` 内的行不翻译**（原样透传）。
- 变量名 / 函数名 / 路径 / URL / 数字 / 公式（`O(n log n)`、`$...$` 等）由提示词约束原样保留。
- 模型未就绪时自动降级为「原样透传」，不报错、不断流。
- 支持 `reasoning_content` 与 `reasoning` 两种字段名。

## 已知限制

- **只对「单独返回 reasoning 字段」的服务商生效**（DeepSeek 等）。若服务商把思考写在正文的
  ` thinking...<｜end▁of▁thinking｜>` 标签里，需要额外解析（当前未做）。
- 流式翻译是「按句/按行」下发的，翻译速度受本机 GPU 影响；若本机同时在跑大模型会明显变慢。
- 代理需与 Chatbox 在同一台机器上（监听 127.0.0.1）。
