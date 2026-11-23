# proc_suspend.ps1 —— 挂起/恢复进程（可连同子进程一起），用于把 GPU 算力让给另一个任务
# 用法:
#   powershell -File proc_suspend.ps1 -Action list
#   powershell -File proc_suspend.ps1 -Action suspend -ProcId 27656 -IncludeChildren
#   powershell -File proc_suspend.ps1 -Action resume  -ProcId 27656 -IncludeChildren
#   powershell -File proc_suspend.ps1 -Action suspend -Match 'work_20261122_142408' -IncludeChildren
# 注意: -ProcId 不要写成 -Pid（$PID 是 PowerShell 保留自动变量）
param(
    [ValidateSet('list', 'suspend', 'resume')] [string]$Action = 'list',
    [int[]]$ProcId = @(),
    [string]$Match = '',
    [switch]$IncludeChildren
)

$ErrorActionPreference = 'Stop'

Add-Type -Namespace NativeProc -Name Api -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
[DllImport("kernel32.dll", SetLastError=true)] public static extern bool CloseHandle(IntPtr h);
[DllImport("ntdll.dll")] public static extern uint NtSuspendProcess(IntPtr h);
[DllImport("ntdll.dll")] public static extern uint NtResumeProcess(IntPtr h);
'@

$PROCESS_SUSPEND_RESUME = 0x0800
$PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate

function Format-Row($p) {
    $cmd = ($p.CommandLine -replace '\s+', ' ')
    if ($cmd.Length -gt 150) { $cmd = $cmd.Substring(0, 150) + '...' }
    '{0,-7} ppid={1,-7} {2,-24} {3}' -f $p.ProcessId, $p.ParentProcessId, $p.Name, $cmd
}

function Get-Descendants([int]$rootPid) {
    $result = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    $queue.Enqueue($rootPid)
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        foreach ($c in $all | Where-Object { $_.ParentProcessId -eq $cur }) {
            if (-not $result.Contains([int]$c.ProcessId)) {
                $result.Add([int]$c.ProcessId)
                $queue.Enqueue([int]$c.ProcessId)
            }
        }
    }
    return $result
}

if ($Action -eq 'list') {
    $rows = $all | Where-Object { $_.Name -match 'python|rife|ffmpeg|yt-dlp|cmd' -and $_.CommandLine }
    foreach ($r in $rows) { Format-Row $r }
    exit 0
}

$targets = New-Object System.Collections.Generic.List[int]
foreach ($id in $ProcId) { if (-not $targets.Contains($id)) { $targets.Add($id) } }
if ($Match) {
    foreach ($p in $all | Where-Object { $_.CommandLine -and ($_.CommandLine -match $Match) }) {
        if (-not $targets.Contains([int]$p.ProcessId)) { $targets.Add([int]$p.ProcessId) }
    }
}
if ($targets.Count -eq 0) { Write-Output '没有匹配到进程'; exit 1 }

$final = New-Object System.Collections.Generic.List[int]
foreach ($t in $targets) {
    if (-not $final.Contains($t)) { $final.Add($t) }
    if ($IncludeChildren) {
        foreach ($d in (Get-Descendants $t)) { if (-not $final.Contains($d)) { $final.Add($d) } }
    }
}

foreach ($id in $final) {
    $h = [NativeProc.Api]::OpenProcess($PROCESS_SUSPEND_RESUME -bor $PROCESS_QUERY_LIMITED_INFORMATION, $false, [int]$id)
    if ($h -eq [IntPtr]::Zero) {
        Write-Output ("[!] 打不开 PID {0}（可能已退出或无权限，err={1}）" -f $id, [Runtime.InteropServices.Marshal]::GetLastWin32Error())
        continue
    }
    try {
        if ($Action -eq 'suspend') { [void][NativeProc.Api]::NtSuspendProcess($h) }
        else { [void][NativeProc.Api]::NtResumeProcess($h) }
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        Write-Output ("[{0}] PID {1} {2}" -f $Action, $id, $(if ($proc) { $proc.ProcessName } else { '?' }))
    }
    finally { [void][NativeProc.Api]::CloseHandle($h) }
}
