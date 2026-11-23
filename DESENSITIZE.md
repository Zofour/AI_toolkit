# 脱敏说明

本目录是**开源前的脱敏副本**，源目录未做任何改动。
生成方式：白名单复制源码 → 对文本文件做定点替换 → 删除不该公开的资产。

- 复制文件：498 个，约 2.3 MB
- 文本改写：54 个文件、124 处命中
- 跳过的做法：整目录排除模型/构建产物/日志/截图，单文件上限 2 MB

## 一、被替换的内容

| 类别 | 原文（已删除） | 替换为 | 处数 |
|---|---|---|---|
| 家目录 | `C:\Users\<真实用户名>` / `C:/Users/<真实用户名>` | `C:\Users\yourname` | 36 |
| 用户名残片 | `<真实用户名>`（出现在 URL、命令行中） | `yourname` | 2 |
| 校园网账号 | 真实学号（10 位） | `2025000000` | 6 |
| 校园网密码 | 真实密码 | `YOUR_PASSWORD` | 2 |
| 中继令牌 | 随机 32 位字符串 | `CHANGE_ME` | 2 |
| FileHub 令牌 | 随机 24 位字符串 | `CHANGE_ME` | 3 |
| Tailscale IP | 本机与手机各一个 100.6x–127.x 段地址（CGNAT） | `100.64.0.1` | 27 |
| 局域网 IP | 192.168.1.x | `192.168.1.100` | 5 |
| 校园网网段 | 10.12.x.x、10.0.0.x | `10.0.0.1` | 9 |
| 校园门户 IP | 202.4.x.x（DNS 失败时的兜底地址） | `202.4.0.1` | 1 |
| K230 热点网关 | 192.168.169.x | `192.168.1.100` | 1 |
| 主机名 | tailscale 机器名（内部代号 z＋两位数字） | `yourpc` | 10 |
| 游戏名 | 具体商业游戏名 / 其 Unity 工程名 | `示例游戏` / `ExampleGame` | 12 |
| 密码样例 | 测试用明文口令（含中文/符号样例） | `CHANGE_ME` | 4 |

> 上表里只写“原值的形态”，不写原值本身——这份文档本身也要开源。

正则兜底规则（对全部文本文件生效）：
`sk-` 开头的 Key、`Bearer <长串>`、`SESSDATA=<长串>`、邮箱、
手机号（1[3-9] 开头 11 位）、以及任意 `100.64–127.x.x` / `192.168.x.x` / `10.x.x.x` 私网地址。

## 二、被删除（未复制）的文件

- **凭据类**：`bili_sessdata.txt`（B 站登录态）、所有真实 `config.json`
  （改成 `config.example.json`，值已脱敏）、`local.properties`（含 SDK 绝对路径）
- **模型/数据**：`*.gguf *.onnx *.ckpt *.safetensors *.kmodel`、`models/`、`osm/*.pbf`
- **构建产物**：`build/ .gradle/ node_modules/ dist/ __pycache__/ .venv/`、
  所有 `*.apk *.exe *.dll *.so`、`deepseek-demo` 里打包好的 `assets/www/`（前端产物，可重建）
- **日志与调试残件**：`*.log *.err *.bak*`、`history.json`、`cache.jsonl`、
  `jp_strings.json`（游戏剧本文本）、`*.png/*.jpg` 截图、uiautomator 的 `ui*.xml` 与 `v*.xml` 转储
- **第三方二进制**：`ai_toolkit/bin`（RIFE）、`ai_toolkit/models`（u2net 抠图模型）、
  `chatbox-bridge/tools`（便携 JDK）、`chatbox-bridge/ts`（tailscale APK/MSI）、
  各工程的 `_shots/`

## 三、保留但值得注意

- `Huawei ALN-AL00` / `Android 12`：仅机型描述，出现在踩坑记录里，不指向个人身份
- `tree.buct.edu.cn`：学校门户域名，是这条工作流的**前提**，公开信息，故保留
- `D:\image_temp`、`C:\chatbox_temp` 等盘符与目录名：属于工作流约定，保留；
  其中 `chatbox_temp` 只是作者自己的目录习惯，可自行改
- 各安卓工程的包名前缀 `com.chatbox.*`：可作为你的命名起点，也可整体改掉

## 四、发布前建议再自查一遍

```powershell
# 1) 家目录 / 学号 / 令牌 / 私网地址（应无输出）
Get-ChildItem <备份目录> -Recurse -File |
  Select-String -Pattern '34151|C:\\Users\\(?!yourname)|2025130131|SESSDATA=|sk-[A-Za-z0-9]{16,}|100\.(6[4-9]|[7-9]\d|1[0-2]\d)\.|192\.168\.|(?<![\d.])10\.\d+\.\d+\.\d+'
# 2) 真实 config.json 是否漏进（应无输出）
Get-ChildItem <备份目录> -Recurse -Filter config.json
# 3) 大文件（>2MB 只应是源码或锁文件）
Get-ChildItem <备份目录> -Recurse -File | Where-Object Length -gt 2MB | Select FullName,Length
```

另外提醒两点：
1. 如果曾经把令牌贴到聊天记录/终端历史里，**请到对应服务重新生成**（脱敏只改了文件，
   已泄露的密钥本身仍然有效）。
2. 安卓工程的 `keystore` / 签名文件未包含在内；release 构建请自建签名。

## 五、重新生成 / 以后新增内容时

本次备份用的是一段一次性脚本（**不随仓库提供**，因为它内嵌了真实替换词，本身就是要被删掉的敏感件）。
它的流程可以直接复用：

1. 白名单项目目录 → 递归遍历
2. 黑名单过滤：目录名（`build .gradle node_modules models bin dist cache __pycache__ .venv tools`）、
   后缀（二进制、模型、媒体、日志）、文件名（`*.log *.bak ui*.xml config.json`）、单文件 2 MB 上限
3. 文本脱敏：先按「字符串规则」再按「正则规则」替换；编码依次尝试 UTF-8+BOM / GBK / UTF-8，
   保留原文件的 BOM 与 CRLF（`.bat` 尤其重要）
4. `config.json` 改名为 `config.example.json`，并在 `.gitignore` 里忽略回去

以后往仓库里加新脚本时，请先过一遍第四节的自查命令。
（注：第四节那段命令本身就含敏感词模式，所以它自己会被扫到，属正常。）
