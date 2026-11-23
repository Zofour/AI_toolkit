# FileHub —— 手机只读访问电脑上的图片/视频

手机（安卓）通过 **Tailscale** 直连电脑，浏览并打开电脑上的图片和视频。
**只读**：服务端只有 GET 接口，没有删除/改名/上传/写入的任何入口。

```
[手机 App]  --HTTP(GET + Range)-->  100.64.0.1:8730  [电脑 Python 服务]
   Compose + Coil + Media3              读 Windows 磁盘上的目录
```

## 目录

```
C:\chatbox_temp\filehub\
├─ server\
│  ├─ filehub_server.py    电脑端服务（Python 标准库 + Pillow + ffmpeg）
│  ├─ config.json          端口 / 令牌 / 共享哪些目录
│  ├─ run.bat              双击启动
│  ├─ selftest.py          服务端自检
│  └─ cache\               缩略图缓存（可随时删）
├─ android\                安卓工程（Kotlin + Compose）
├─ build_apk.bat           重新构建 APK
└─ README.md               本文件
```

## 一、电脑端

1. 双击 `server\run.bat`（或用 `python server\filehub_server.py`）。
   窗口会打印 Tailscale 地址、局域网地址和令牌。
2. 保持窗口开着。关掉窗口 = 手机连不上。
3. **整台电脑的磁盘全自动共享**（`config.json` 的 `"auto_drives": true`）：
   启动时枚举所有本地盘与可移动盘（U 盘、移动硬盘），手机端直接看到 `C盘` `D盘` `G盘 U盘` 这样一项。
   空读卡器、光驱、网络盘会跳过；系统目录（`$RECYCLE.BIN` / `System Volume Information` / `Config.Msi`）
   和 `Documents and Settings` 这类 junction 也会自动过滤，不刷存视。
   **中途插的 U 盘不用重启服务**，App 里点右上角刷新就出来了。
4. 想额外固定几个常用目录（不放也能用），改 `server\config.json` 的 `roots`，键名就是手机上显示的名字。

```jsonc
{
  "auto_drives": true,          // 全盘共享；false 就只共享下面的 roots
  "roots": {                    // 常用目录快捷方式（可选）
    "图片": "C:/Users/yourname/Pictures",
    "视频": "C:/Users/yourname/Videos",
    "AI生图": "D:/image_temp"
  }
}
```

安全：服务绑在 `0.0.0.0`，但每个请求都校验令牌（`?t=...`）。
令牌不对返回 401；`..` 穿越路径一律拒绝（只允许在共享根之内）。
**注意**：全盘共享等于把 C:\ 也包括进去了，虽然服务层没有任何写/删接口，
但令牌泄露就等于别人能读你整个电脑——不要把带令牌的地址发给别人。
想换令牌：改 `config.json` 的 `token`，App 里“设置”改成一样的即可。

端口被占用就改 `config.json` 的 `port`，App 端地址跟着改。

## 二、桌面快捷方式与开机自启

- **桌面**：`FileHub 服务.lnk`（图标用的是 App 的图标），双击即启动服务
- **开机自启**：同一个快捷方式已放进
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`\
  登录后自动以**最小化**窗口启动，不打扰你
- 已启动过再双击不会报错：`run.bat` 先检查 8730 端口，发现已在跑就提示一下退出
- **启动后窗口自动移到桌面 2**（虚拟桌面索引 1），不占当前桌面；由 `config.json` 的 `"move_to_desktop": 1` 控制，改成 `0` 或删掉这行就不搬
- 取消自启：删掉启动文件夹里那个快捷方式即可（`Win+R` 输入 `shell:startup`）

## 三、手机端

APK：`android\app\build\outputs\apk\debug\app-debug.apk`
（已装到这台手机：`adb install -r <apk>`）

首次打开会要求确认地址与令牌，默认已经填好
`http://100.64.0.1:8730` + 内置令牌 —— 点「测试连接」→「保存并进入」。

- 主界面：根目录（图片/视频/桌面/下载/AI生图）→ 点文件夹进入 → 点图片/视频打开
- 图片：左右滑动切换、双指缩放、双击放大、单击隐藏上下信息条
- **横屏查看**：查看页右上角有旋转按钮，一点就转成横屏（左右两个方向都行），再点回竖屏；
  退出查看页会自动恢复“跟随系统”，不会让整个 App 卡在横屏
- 大图（>6 MB）默认用电脑端生成的 2200px 预览秒开，右下角「原图」可加载全尺寸
- 视频：点播放，进度条可随意拖动（服务端支持 HTTP Range）
- **桌面上的 `.lnk` 快捷方式也能看**：只要快捷方式指向的是图片/视频，手机里就直接当成图片/视频显示（自动解析目标，名字去掉 `.lnk`）；指向文件夹的快捷方式当一个文件夹点进去；指向已删文件的死链自动隐藏
- **`.flv` 直接能播**（Media3 自带 FLV 提取器，靠嗅探识别，不需要转码）：
  实测 30 分钟 / 707 MB 的 1080p FLV，点开约 0.45 秒出画面，时长显示准确，跳转后约 0.15 秒恢复播放
- 右上角：排序（名称/时间）、刷新、设置

局域网里也可以不走 Tailscale：把地址改成 `http://192.168.1.100:8730`（更快）。

## 四、重新构建 APK

```
C:\chatbox_temp\filehub\build_apk.bat
```

日志在 `build.log`，成功会打印 `BUILD SUCCESSFUL`。

## 五、排错

| 现象 | 原因 / 处理 |
|---|---|
| App 显示“连接失败” | 电脑上 run.bat 没开；或手机 Tailscale 没连上（`ping 100.64.0.1` 试一下） |
| “令牌不对” | config.json 的 token 和 App 里填的不一致 |
| 缩略图转圈不出来 | 视频缩略图要 ffmpeg 抽帧，第一次每张约 0.3–1 s，之后走缓存 |
| 视频黑屏但有声音 | 极少数机型 SurfaceView 兼容问题；本工程已用 TextureView |
| 新插的 U 盘在 App 里看不到 | 点主界面右上角刷新（或退出重进根目录）；空读卡器不显示是正常的 |
| 某个目录点进去报“没有权限” | 那个目录系统就不让读（如部分系统目录），跳过即可 |
| 端口被占用 | 改 config.json 的 port，App 地址同步改 |
| 电脑重启后手机连不上 | 登录后等 2 秒（自启要 python 起一下）；还是不行就双击桌面快捷方式 |
| 双击快捷方式无反应 | 多半是服务已经在跑（最小化窗口在任务栏里找一下） |

## 六、服务端接口（只读）

```
GET /api/ping                                   → {ok, name, roots}
GET /api/roots                                  → 根目录列表
GET /api/list?path=<相对路径>&sort=name|date     → 目录内容（默认只返回文件夹+图片+视频）
GET /f?path=<相对路径>                          → 原文件，支持 Range
GET /t?path=<相对路径>&w=360                    → 缩略图 JPEG（磁盘缓存）
```

所有接口都需要 `?t=<token>`（或 `X-Token` 头）。
