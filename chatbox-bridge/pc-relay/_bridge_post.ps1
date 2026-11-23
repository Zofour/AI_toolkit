<#
  _bridge_post.ps1 —— Chatbox Bridge 窗口归位脚本

  作用：把 Bridge 的启动器 / 中继 / 注入器窗口移动到指定虚拟桌面（默认桌面 2 = 索引 1）。
  由 start_bridge.bat 在启动中继与注入器之后调用（第 4/4 步），保证开机自启后窗口不堆在桌面 1。

  设计约束（重要）：
    * 幂等：重复执行不会重复建桌面，已在目标桌面上的窗口直接跳过
    * 不打扰：不切换当前桌面；若因建桌面被迫切换，结束前切回原桌面
    * 不杀进程：全程只做窗口移动与桌面枚举，绝不结束或重启任何进程
    * 不阻塞启动：任何异常都只打印警告并 exit 0，不影响 Bridge 本身运行

  用法：
    powershell -NoProfile -ExecutionPolicy Bypass -File _bridge_post.ps1
    powershell ... -File _bridge_post.ps1 -Desktop 1 -WaitSeconds 40 -NoLauncher
#>
param(
    [int]$Desktop = 1,
    [int]$WaitSeconds = 40,
    [string]$VdExe = '',
    [switch]$NoLauncher
)

$ErrorActionPreference = 'Continue'

function Say([string]$m) { Write-Host ("   " + $m) }

# ---------- 1. 定位虚拟桌面工具 ----------
if (-not $VdExe -or -not (Test-Path $VdExe)) {
    $cand = @('C:\Users\yourname\Tools\VirtualDesktop\VirtualDesktop11-24H2.exe')
    $gc = Get-Command vd -ErrorAction SilentlyContinue
    if ($gc) { $cand += $gc.Source }
    $VdExe = ($cand | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
}
if (-not $VdExe) {
    Say 'WARN: 未找到 VirtualDesktop 工具，跳过窗口归位（Bridge 不受影响）'
    exit 0
}
Say "桌面工具: $VdExe"

function Vd { (& $VdExe @args 2>&1 | Out-String) }

# ---------- 2. 窗口枚举（Win32） ----------
if (-not ('BridgeWinFinder' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class BridgeWinFinder {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    public static List<string> Find(string prefix) {
        List<string> res = new List<string>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            StringBuilder sb = new StringBuilder(512);
            GetWindowText(h, sb, 512);
            string t = sb.ToString();
            if (t.Length > 0 && t.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) {
                res.Add(h.ToInt64().ToString() + "\t" + t);
            }
            return true;
        }, IntPtr.Zero);
        return res;
    }
}
"@ -ErrorAction Stop
}

# ---------- 3. 等待窗口出现 ----------
$prefix = 'Chatbox Bridge'
Say "等待 Bridge 窗口出现（最多 $WaitSeconds 秒）..."
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$found = @()
while ((Get-Date) -lt $deadline) {
    $found = @([BridgeWinFinder]::Find($prefix))
    $nRelay = @($found | Where-Object { $_ -match 'Relay' }).Count
    $nInj = @($found | Where-Object { $_ -match 'Injector' }).Count
    if ($nRelay -ge 1 -and $nInj -ge 1) { break }
    Start-Sleep -Milliseconds 500
}
if ($found.Count -eq 0) {
    Say 'WARN: 没找到 Bridge 窗口，跳过归位'
    exit 0
}
Say ("找到 {0} 个 Bridge 窗口" -f $found.Count)

# 分类：含 Relay / Injector 的是一线窗口，其余视为启动器窗口
$targets = @()
foreach ($w in $found) {
    $parts = $w -split "`t", 2
    $h = $parts[0]
    $title = if ($parts.Count -gt 1) { $parts[1] } else { '' }
    $isLauncher = ($title -notmatch 'Relay') -and ($title -notmatch 'Injector')
    if ($isLauncher -and $NoLauncher) { Say "跳过启动器窗口: $title"; continue }
    $targets += [pscustomobject]@{ Handle = $h; Title = $title; Launcher = $isLauncher }
}
if ($targets.Count -eq 0) { Say '没有需要搬移的窗口'; exit 0 }

# ---------- 4. 确保目标桌面存在 ----------
$countOut = Vd /Count
$count = 0
if ($countOut -match 'Count of desktops:\s*(\d+)') { $count = [int]$Matches[1] }
if ($count -le 0) { $count = 1 }

$curOut = Vd /GetCurrentDesktop
$cur = 0
if ($curOut -match 'desktop number (\d+)') { $cur = [int]$Matches[1] }
Say "当前共 $count 个桌面，当前在第 $($cur + 1) 个"

$created = 0
while ($count -le $Desktop) {
    Vd /New | Out-Null
    $count++
    $created++
}
if ($created -gt 0) { Say "已创建 $created 个桌面" }

# 建桌面一般不会切换；万一被切走，切回原桌面
$cur2Out = Vd /GetCurrentDesktop
if ($cur2Out -match 'desktop number (\d+)') {
    $cur2 = [int]$Matches[1]
    if ($cur2 -ne $cur) {
        Vd "/Switch:$cur" | Out-Null
        Say "检测到桌面被切换，已切回第 $($cur + 1) 个"
    }
}

# ---------- 5. 逐窗口迁移 ----------
$okCount = 0
foreach ($t in $targets) {
    $posOut = Vd "/GetDesktopFromWindowHandle:$($t.Handle)"
    $curD = -1
    if ($posOut -match 'desktop number (\d+)') { $curD = [int]$Matches[1] }
    if ($curD -eq $Desktop) { Say "[已就位] $($t.Title)"; $okCount++; continue }

    $done = $false
    for ($i = 1; $i -le 3; $i++) {
        Vd "/GetDesktop:$Desktop" "/MoveWindowHandle:$($t.Handle)" | Out-Null
        Start-Sleep -Milliseconds 400
        $after = Vd "/GetDesktopFromWindowHandle:$($t.Handle)"
        if ($after -match "desktop number $Desktop \(") { $done = $true; break }
    }
    if ($done) { Say "[已移动] $($t.Title)  ->  桌面 $($Desktop + 1)"; $okCount++ }
    else       { Say "[失败]   $($t.Title)（窗口可能已关闭）" }
}

Say "归位完成: $okCount / $($targets.Count) 个窗口位于桌面 $($Desktop + 1)"
exit 0
