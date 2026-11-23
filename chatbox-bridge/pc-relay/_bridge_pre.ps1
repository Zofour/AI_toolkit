function PortOpen { return (Test-NetConnection -ComputerName 127.0.0.1 -Port 9333 -WarningAction SilentlyContinue).TcpTestSucceeded }
# 先清掉可能残留的中继/注入器，避免重复实例（重复注入会发两遍）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'run\.py|chatbox_inject' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if (PortOpen) { Write-Host "   Chatbox debug port already open (9333)"; exit 0 }
Write-Host "   Restarting Chatbox with --remote-debugging-port=9333 ..."
Get-Process Chatbox -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 3
$exe = "C:\Program Files\Chatbox\Chatbox.exe"
if (-not (Test-Path $exe)) { Write-Host "   ERROR: Chatbox.exe not found"; exit 1 }
Start-Process $exe -ArgumentList "--remote-debugging-port=9333"
for ($i = 0; $i -lt 40; $i++) { Start-Sleep 1; if (PortOpen) { Write-Host "   debug port ready"; exit 0 } }
Write-Host "   WARN: port 9333 not ready after 40s"