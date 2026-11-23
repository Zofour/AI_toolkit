# BUCT 校园网自动登录 —— 安装开机自启
# 用法（普通权限即可）：
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Task    # 用计划任务（可自动重启进程）
param([switch]$Task)

$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs  = Join-Path $base 'start_hidden.vbs'
$script = Join-Path $base 'srun_autologin.py'

if (-not (Test-Path $script)) { throw "找不到 $script" }
if (-not (Test-Path $vbs))    { throw "找不到 $vbs" }

# 1) 先杀掉已在跑的实例，避免重复
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*srun_autologin.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if ($Task) {
    # ---- 方式 A：计划任务（登录时触发，异常退出自动重启） ----
    $pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    if (-not $pyw) {
        $pyw = Join-Path (Split-Path (Get-Command python.exe).Source) 'pythonw.exe'
    }
    if (-not (Test-Path $pyw)) { throw "找不到 pythonw.exe" }

    $action  = New-ScheduledTaskAction -Execute $pyw -Argument "`"$script`"" -WorkingDirectory $base
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
    Register-ScheduledTask -TaskName 'BUCT_AutoLogin' -Action $action -Trigger $trigger `
        -Settings $settings -Description 'BUCT 校园网断网自动登录' -Force | Out-Null
    Write-Host "[OK] 已注册计划任务 BUCT_AutoLogin" -ForegroundColor Green
}
else {
    # ---- 方式 B：启动文件夹（最简单，无需管理员） ----
    $startup = [Environment]::GetFolderPath('Startup')
    $lnkPath = Join-Path $startup 'BUCT_AutoLogin.lnk'
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($lnkPath)
    $lnk.TargetPath       = "$env:SystemRoot\System32\wscript.exe"
    $lnk.Arguments        = "`"$vbs`""
    $lnk.WorkingDirectory = $base
    $lnk.WindowStyle      = 7
    $lnk.Description      = 'BUCT 校园网断网自动登录'
    $lnk.Save()
    Write-Host "[OK] 已加入开机启动：$lnkPath" -ForegroundColor Green
}

# 2) 立即在后台启动一次
Start-Process -FilePath 'wscript.exe' -ArgumentList "`"$vbs`"" -WindowStyle Hidden
Write-Host "[OK] 已在后台启动守护进程，日志：$base\autologin.log" -ForegroundColor Green
