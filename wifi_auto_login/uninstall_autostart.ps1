# BUCT 校园网自动登录 —— 卸载开机自启
$ErrorActionPreference = 'SilentlyContinue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*srun_autologin.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "[OK] 已结束进程 $($_.ProcessId)" }

$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'BUCT_AutoLogin.lnk'
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host '[OK] 已移除启动文件夹快捷方式' }

Unregister-ScheduledTask -TaskName 'BUCT_AutoLogin' -Confirm:$false
Write-Host '[OK] 已清理计划任务（如存在）'
