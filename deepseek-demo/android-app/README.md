# DeepSeek 网页版 → 安卓壳（chat-demo + WebView）

把官方开源前端 [deepseek-ai/chat-demo](https://github.com/deepseek-ai/chat-demo)（MIT）直接打进 APK，无自建后端。

## 结构

```
deepseek-demo/                 官方前端源码（git clone，未改一行）
  dist/                        npx rspack build -c rspack.config.ts 的产物
  android-app/                 本壳工程（纯 Java，零第三方依赖）
    app/src/main/assets/www/   由 sync_web.ps1 从 dist 同步
    app/src/main/java/com/deepseekdemo/app/MainActivity.java
    app/src/main/res/raw/inject.js    注入脚本（blob 保存 / 主题色上报 / window.open）
    sync_web.ps1               同步 dist → assets/www
    build_apk.bat              一键：同步 + 构建 debug APK
    cdp.mjs                    WebView 远程调试客户端（list / eval / tap / shot / reload）
```

## 构建

```powershell
cd C:\chatbox_temp\deepseek-demo
npx rspack build -c rspack.config.ts        # 出 dist/
cd android-app
powershell -File sync_web.ps1
powershell -File C:\chatbox_temp\ai_toolkit\apk_build.ps1 -Project . -Variant debug -NoDaemon
```

APK: `android-app\app\build\outputs\apk\debug\app-debug.apk`

## 关键设计（改了什么、为什么）

| 问题 | 做法 |
|---|---|
| 需要安全上下文才能录音 | 页面走 `https://appassets.androidplatform.net/`，资源由 `shouldInterceptRequest` 从 assets 读出（等价 WebViewAssetLoader，但零依赖） |
| 不用 `file://` | 避开 null origin 下 IndexedDB/fetch 异常，且录音、AudioContext 可用 |
| API 跨域 | 实测 api.deepseek.com 反射任意 Origin，**不需要代理**，前端直连 |
| 麦克风 | `WebChromeClient.onPermissionRequest` → 运行时申请 `RECORD_AUDIO` → 授权后 grant audio capture |
| 附件/导入 | `onShowFileChooser` → ACTION_GET_CONTENT，`parseResult` 回传给 WebView |
| 导出会话 ZIP | blob 下载在 WebView 里下不了 → `inject.js` 拦截 `<a download>` + blob URL，分块 base64 过 JS 桥，写入「下载」（API29+ MediaStore） |
| 状态栏配色 | 页面主题色写在 `meta[name=theme-color]`，注入脚本监听后 `bridge.setThemeColor()` → 原生同步状态栏/导航栏与图标明暗 |
| 返回键 | 先给页面派发 `Escape`（关弹窗/菜单），2 秒内再按退出，避免一按就杀 |
| 旋转/键盘 | `configChanges` 保住 WebView 不重建；`adjustResize` + 页面自带 visualViewport 逻辑，输入框跟随键盘 |
| 外链 | `shouldOverrideUrlLoading` 非本域一律丢给系统浏览器 |

## 远程调试

```powershell
$p = (adb shell pidof com.deepseekdemo.app).Trim()
adb forward tcp:9222 localabstract:webview_devtools_remote_$p
cd android-app
node cdp.mjs list
node cdp.mjs eval "location.origin"
node cdp.mjs tap 260 739        # CSS 像素坐标
node cdp.mjs shot out.png
```

## 模型切换（自定义，官方 demo 没有）

官方 chat-demo 把模型写死为 `deepseek-flash`（`types.ts` 里其实已声明 `'deepseek-flash' | 'deepseek-v4-pro'`）。本项目改成可选：

- 入口 1：输入栏第三个开关「专家模式」（星形图标，图标模式节省宽度）
- 入口 2：设置 → 通用设置 → 模型 → `Flash` / `V4 Pro（专家模式）`
- 存在 `localStorage['chat-demo:model']`，默认 `deepseek-flash`
- 每条新消息按当前设置取模型；同一会话里切换即时生效

**pro 的接口限制（实测结论，务必知道）**

在 `POST /anthropic/v1/messages` 上逐字段探测 `deepseek-v4-pro`：

| 请求字段 | pro 结果 |
|---|---|
| 最小请求（model/system/messages/max_tokens） | 200 |
| `thinking: {type:'enabled'}` | 200（支持思考） |
| `safety_check: {level:'high'}` | 200 |
| `tools: []` | 200 |
| `tools: [deepseek_read_url]` | **400** |
| `tools: [deepseek_web_search]` | **400** |
| `title: {enabled:true}` | **400** |

报错原文：`The server-side tool calls (deepseek_web_search, deepseek_read_url) and the title generation feature are unavailable for model deepseek-v4-pro.`

所以 `store.ts` 在 pro 下按模型裁剪请求：`tools: []`、不发 `title`、不发 `latest_reminder`；输入栏的「智能搜索」在专家模式下被禁用。副作用是 **pro 会话不会自动生成标题**（显示“新对话”），需要手动重命名。图片理解也只有 Flash 支持，专家模式下传图会报错。

文件改动：`services/settings.ts`（model 字段 + setModel）、`services/chat/store.ts`（裁剪请求）、`components/chatInput/ChatInput.tsx`（开关）、`components/settings/SettingsDialog.tsx`（模型下拉）、`components/base/icons.tsx`（新图标）、`i18n/{zh,en}.ts`。

## 修复记录：多选文件上传无效（v1.2.0）

现象：一次选 2 张以上图片后点“选择”，选择器关闭但草稿区没有任何附件，没有报错。

排查：`adb logcat -s DSDemo:D` 打印入参，得到

```
onActivityResult code=-1 dataNull=false clipCount=2 uris=null
```

`resultCode=RESULT_OK`、`clipData` 有 2 项、系统也把 `content://...image:328022/328023` 的读权限授给了本应用，但 `WebChromeClient.FileChooserParams.parseResult()` 返回 **null** —— WebView 于是把整批结果丢弃，页面 `input.files` 为空。

修复：不再依赖 `parseResult()`，改为自己从 `Intent` 取 URI（`collectPickedUris()`）：先遍历 `getClipData()`，没有则退回 `getData()`；`RESULT_CANCELED` 时返回 null。

验证：`uris=2` → 页面收到两个 `File`（约 1 MB / 张）→ 两次 `/files` 上传 200 → 发消息后模型正确描述了这两张图。

## 已知限制

- **导出文件落在 `内部存储/Download/`**（API 29+ 走 MediaStore，写入后弹原生提示框显示完整路径并提供「打开」；同名文件会自动加 `(1)`）。Android 9 及以下落到应用私有目录，弹窗里给的是绝对路径。
- API Key 明文存在 `localStorage`（页面原生行为），仅适合自用；要分发建议改为原生 Keystore 注入。
- 没有推送、后台保活、系统分享、多设备同步（纯前端无后端）。
- 只适合自用/侧载，名字带 DeepSeek 上架有商标风险。
- 需系统 WebView ≥ Chrome 105（本机测试机为 132）；低于此版本启动时会提示。
