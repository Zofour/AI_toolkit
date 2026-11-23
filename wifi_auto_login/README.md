# BUCT 校园网自动登录（srun / tree.buct.edu.cn）

检测到断网（未认证）就自动帮你登录，纯 Python 标准库，无第三方依赖。

## 文件清单

| 文件 | 作用 |
|---|---|
| `config.json` | 账号密码与参数（**先改这个**） |
| `srun_autologin.py` | 主程序：状态检测 + 登录 + 守护循环 |
| `start_hidden.vbs` | 无窗口启动（开机自启用） |
| `start_daemon.bat` | 桌面快捷方式指向它：启动守护并显示当前在线状态 |
| `autologin.lock` | 单实例锁，重复启动不会产生多个守护进程 |
| `install_autostart.ps1` | 安装开机自启并立刻后台启动 |
| `uninstall_autostart.ps1` | 卸载开机自启并结束进程 |
| `autologin.log` | 运行日志（自动滚动，超过 2MB 归档为 .1） |
| `tests/` | 与门户 JS 对照的加密校验脚本（可选，不用管） |

## 三步用起来

1. 编辑 `config.json`，把 `password` 改成你的校园网密码（`username` 已填 `2025000000`，不对就一起改）。
2. 先手动验一次：
   ```powershell
   python srun_autologin.py --status     # 看当前是否在线
   python srun_autologin.py --login      # 强制登录一次
   ```
3. 装开机自启（后台常驻，无窗口）：
   ```powershell
   powershell -ExecutionPolicy Bypass -File install_autostart.ps1
   ```

桌面上的「**校园网自动登录**」快捷方式 = 启动守护（后台）+ 显示当前在线状态，双击即用；重复双击不会开第二个进程。

## 常用命令

```powershell
python srun_autologin.py            # 前台常驻：每 15s 检测，断网立刻登录
python srun_autologin.py -v         # 同上，带详细请求日志
python srun_autologin.py --once     # 只检查一次，必要时登录（适合交给任务计划每分钟跑）
python srun_autologin.py --status   # 只打印在线状态
python srun_autologin.py --login    # 强制登录
powershell -ExecutionPolicy Bypass -File uninstall_autostart.ps1   # 停止并卸载
```

想用「计划任务 + 自动重启进程」而不是启动文件夹：
```powershell
powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Task
```

## 工作原理（与门户前端完全一致）

1. `GET /cgi-bin/rad_user_info` → `error:"ok"` 即已在线；`not_online_error` 即掉线。
2. `GET /cgi-bin/get_challenge` → 取 `challenge`（token）与 `client_ip`。
3. 计算：
   - `hmd5   = md5(token + password)`
   - `info   = "{SRBX1}" + base64_自定义字母表( XXTEA( JSON{username,password,ip,acid,enc_ver}, token ) )`
   - `chksum = sha1(token+user+token+hmd5+token+ac_id+token+ip+token+n+token+type+token+info)`
4. `GET /cgi-bin/srun_portal?action=login&password={MD5}hmd5&info=...&chksum=...`
5. 成功后用 `rad_user_info` 复核。

加密实现已用 Node 跑门户原版 `Portal.js` 的 `encode/s/l` 函数逐字节对照，`info`、`hmd5`、`chksum` 完全一致（含中文密码场景）。

## 参数说明（config.json）

| 键 | 默认 | 说明 |
|---|---|---|
| `portal` | `https://tree.buct.edu.cn` | 认证门户地址 |
| `ac_id` | `20` | 认证设备编号，就是你登录页地址里的 `ac_id=20` |
| `username` / `password` | — | 校园网账号密码（密码明文存本机） |
| `check_interval` | 15 | 在线时的检测间隔（秒），不宜太小 |
| `retry_interval` | 20 | 登录失败首次重试间隔（秒） |
| `max_retry_interval` | 300 | 连续失败的最大退避（秒），防密码错误把账号试锁 |
| `timeout` | 8 | 单次 HTTP 超时 |
| `verify_ssl` | false | 认证前证书可能是内网自签；如遇证书问题保持 false |
| `skip_if_public_ip` | true | 出口 IP 是公网地址（不在校园网）时不发登录请求 |
| `device` / `platform` | `Windows 10` / `Windows` | 上报给网关的设备信息 |

## 常见问题

- **日志报 `登录失败: ... password` 之类**：密码错了。连错几次会被网关锁定一段时间，脚本已做退避，但请先改对密码。
- **`ip_already_online_error`**：该出口 IP 已经有人登录（比如路由器或同网段其他设备），本机其实能上网，脚本视为成功。
- **`skip_if_public_ip` 提示不在校园网**：说明当前连的是别的网络（如手机热点），不会乱发登录请求。
- **宿舍路由器 NAT 场景**：校园网只看到路由器的出口 IP，任何一台设备登录后全屋都能上网；脚本在任一设备上跑都能生效。
- **想确认它真的在工作**：`Get-Content autologin.log -Tail 20`，日志里断网时会有一条「检测到未认证（ip=...），开始登录…」+「登录成功」。
- **电脑睡眠唤醒后不用管**：守护进程会自己重试；如果它被系统结束，重新运行 `install_autostart.ps1` 即可。

## 安卓 App（免 root，前台常驻）

源码在 `android/`，成品 APK：**`BUCT-WiFi-1.0.apk`**（约 110 KB，debug 签名，可直接侧载）。

### 功能

- 前台服务 + 通知栏常驻，默认每 15 秒查一次 `/cgi-bin/rad_user_info`，未认证就立刻登录（协议与桌面版**同一套**，加密已用 Java ↔ Python ↔ 门户 JS 三方逐字节对齐）。
- 开机自启（`BOOT_COMPLETED` / `LOCKED_BOOT_COMPLETED` / `QUICKBOOT_POWERON` / `MY_PACKAGE_REPLACED`）。
- 一键授权入口：通知权限、电池优化白名单、各家 ROM 的「自启动」管理页。
- 界面里直接看运行日志；支持「立即检测」「停止」「清空日志」。

### 安装

```powershell
adb install -r C:\chatbox_temp\wifi_auto_login\BUCT-WiFi-1.0.apk
# 或者把 apk 拷到手机，用文件管理器点开安装（需允许安装未知来源）
```

### 配置（两种方式）

1. App 里手填账号 / 密码 / ac_id / 间隔 → 点「保存并启动」。
2. 命令行一键配置（适合重装后快速恢复）：
   ```powershell
   adb shell am start -n com.chatbox.buctwifi/.MainActivity --es user 2025000000 --es pass YOUR_PASSWORD --es acid 20 --es interval 15
   adb shell pm grant com.chatbox.buctwifi android.permission.POST_NOTIFICATIONS
   adb shell cmd deviceidle whitelist +com.chatbox.buctwifi
   ```

### 权限说明

清单里已申请：`INTERNET`、`ACCESS_NETWORK_STATE`、`ACCESS/CHANGE_WIFI_STATE`、`CHANGE_NETWORK_STATE`、
`FOREGROUND_SERVICE(+SPECIAL_USE/DATA_SYNC)`、`WAKE_LOCK`、`RECEIVE_BOOT_COMPLETED`、
`POST_NOTIFICATIONS`、`VIBRATE`、`REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`；网络安全配置放开明文 + 用户证书。

**注意**：这些都是「普通 App 能给到的最高档」，真正的 root/系统级权限（`WRITE_SECURE_SETTINGS`、自启动开关）
Android 不允许普通 App 自行获取——华为/荣耀/小米必须在系统设置里手动允许「自启动」，App 内「自启动设置」按钮会直接跳到对应页面。

### 重新构建

```powershell
double-click android\build_apk.bat
# 或者
powershell -File C:\chatbox_temp\ai_toolkit\apk_build.ps1 -Project C:\chatbox_temp\wifi_auto_login\android -NoDaemon
```

### 已实测

真机 HONOR ANY-AN00 / Android 13：安装、前台服务常驻、状态解析全部正常（通知栏显示「在线 2025000000 IP=… 已用=… MB」）。

## 安全提示
- 密码以明文存在 `config.json`，请勿把该目录发给别人；建议把该文件夹放在只属于自己的用户目录下。
- 本脚本只调用你所在校园网的认证接口，不向任何第三方发送数据。
