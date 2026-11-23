<#
  win_to_desktop.ps1 —— 把指定标题前缀的窗口移动到指定虚拟桌面（通用版）

  依赖：MScholtes/VirtualDesktop 的 VirtualDesktop11-24H2.exe（本机已装于
        C:\Users\yourname\Tools\VirtualDesktop\，并在用户 PATH 中，短名 vd.exe）

  示例：
    # 把所有标题以 "Chatbox Bridge" 开头的窗口搬到桌面 2（索引 1）
    powershell -NoProfile -ExecutionPolicy Bypass -File win_to_desktop.ps1 -TitlePrefix "Chatbox Bridge"

    # 搬记事本到桌面 3，且不新建桌面（缺桌面时自动补建，除非 -NoCreate）
    powershell -File win_to_desktop.ps1 -TitlePrefix "记事本" -Desktop 2

    # 只看不搬（打印匹配到的窗口与所在桌面）
    powershell -File win_to_desktop.ps1 -TitlePrefix "Chatbox Bridge" -WhatIf

  设计约束：
    * 幂等：已在目标桌面上的窗口直接跳过；桌面已存在就不新建
    * 不打扰：不切换当前桌面；若建桌面导致切换，结束前切回
    * 不杀进程：只做窗口移动与桌面枚举
    * 不按进程名匹配：避免误伤同名 python.exe / node.exe
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$TitlePrefix,
    [int]$Desktop = 1,
    [int]$WaitSeconds = 15,
    [int]$MinWindows = 1,
    [string]$ExcludePattern = '',
    [string]$VdExe = '',
    [switch]$NoCreate
)

$ErrorActionPreference = 'Continue'
function Say([string]$m) { Write-Host ("   " + $m) }

# ---------- vd.exe ----------
if (-not $VdExe -or -not (Test-Path $VdExe)) {
    $cand = @('C:\Users\yourname\Tools\VirtualDesktop\VirtualDesktop11-24H2.exe',
              'C:\Users\yourname\Tools\VirtualDesktop\vd.exe')
    $gc = Get-Command vd -ErrorAction SilentlyContinue
    if ($gc) { $cand += $gc.Source }
    $VdExe = ($cand | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1)
}
if (-not $VdExe) { Say 'ERROR: 找不到 VirtualDesktop 可执行文件（见 INDEX.md 第 13 节）'; exit 2 }
Say "工具: $VdExe"
function Vd { (& $VdExe @args 2>&1 | Out-String) }

# ---------- 枚举窗口 ----------
if (-not ('WinDesk' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WinDesk {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    public static List<string> Find(string prefix) {
        List<string> res = new List<string>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            StringBuilder sb = new StringBuilder(512);
            GetWindowText(h, sb, 512);
            string t = sb.ToString();
            if (t.Length > 0 && t.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) {
                uint pid; GetWindowThreadProcessId(h, out pid);
                res.Add(h.ToInt64().ToString() + "\t" + pid.ToString() + "\t" + t);
            }
            return true;
        }, IntPtr.Zero);
        return res;
    }
}
"@ -ErrorAction Stop
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$hits = @()
while ((Get-Date) -lt $deadline) {
    $hits = @([WinDesk]::Find($TitlePrefix))
    if ($hits.Count -ge $MinWindows) { break }
    Start-Sleep -Milliseconds 400
}
if ($hits.Count -eq 0) { Say "没找到标题以「$TitlePrefix」开头的窗口"; exit 1 }
Say ("匹配到 {0} 个窗口" -f $hits.Count)

$targets = @()
foreach ($w in $hits) {
    $p = $w -split "`t", 3
    $title = $p[2]
    if ($ExcludePattern -and $title -match $ExcludePattern) { Say "排除: $title"; continue }
    $targets += [pscustomobject]@{ Handle = $p[0]; Pid = $p[1]; Title = $title }
}

# ---------- 目标桌面 ----------
$count = 0
if ((Vd /Count) -match 'Count of desktops:\s*(\d+)') { $count = [int]$Matches[1] }
if ($count -le 0) { $count = 1 }
$cur = 0
if ((Vd /GetCurrentDesktop) -match 'desktop number (\d+)') { $cur = [int]$Matches[1] }
Say "共 $count 个桌面，当前第 $($cur + 1) 个；目标第 $($Desktop + 1) 个"

$created = 0
if ($count -le $Desktop) {
    if ($NoCreate) { Say 'ERROR: 目标桌面不存在且指定了 -NoCreate'; exit 3 }
    while ($count -le $Desktop) { Vd /New | Out-Null; $count++; $created++ }
    Say "已新建 $created 个桌面"
    if ((Vd /GetCurrentDesktop) -match 'desktop number (\d+)') {
        if ([int]$Matches[1] -ne $cur) { Vd "/Switch:$cur" | Out-Null; Say "已切回原桌面" }
    }
}

# ---------- 迁移 ----------
$ok = 0
foreach ($t in $targets) {
    $curD = -1
    if ((Vd "/GetDesktopFromWindowHandle:$($t.Handle)") -match 'desktop number (\d+)') { $curD = [int]$Matches[1] }
    if ($curD -eq $Desktop) { Say "[已就位] $($t.Title)"; $ok++; continue }
    if (-not $PSCmdlet.ShouldProcess($t.Title, "移动到桌面 $($Desktop + 1)")) { continue }
    $done = $false
    for ($i = 1; $i -le 3; $i++) {
        Vd "/GetDesktop:$Desktop" "/MoveWindowHandle:$($t.Handle)" | Out-Null
        Start-Sleep -Milliseconds 400
        if ((Vd "/GetDesktopFromWindowHandle:$($t.Handle)") -match "desktop number $Desktop \(") { $done = $true; break }
    }
    if ($done) { Say "[已移动] $($t.Title) -> 桌面 $($Desktop + 1)"; $ok++ }
    else { Say "[失败]   $($t.Title)（窗口可能已关闭或句柄失效）" }
}
Say "完成: $ok / $($targets.Count) 个窗口位于桌面 $($Desktop + 1)"
exit 0
