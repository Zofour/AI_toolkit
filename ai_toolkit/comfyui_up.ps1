# Ensure ComfyUI is running on :8000. Returns quickly. If down, launches detached and reports.
param([int]$MaxWaitSec = 90)
$ErrorActionPreference = 'SilentlyContinue'
$probe = {
  try { $r = Invoke-RestMethod 'http://127.0.0.1:8000/system_stats' -TimeoutSec 4
        return @{ ok = $true; dev = ($r.devices | Select-Object -First 1) } } catch { return @{ ok = $false } }
}
$s = & $probe
if ($s.ok) { Write-Output ("ALREADY_UP " + $s.dev.name + " vram_free=" + $s.dev.vram_free); exit 0 }

$bat = 'C:\chatbox_temp\ai_toolkit\comfyui_start.bat'
Start-Process -FilePath 'cmd.exe' -ArgumentList ('/c "' + $bat + '"') -WindowStyle Hidden | Out-Null

$deadline = (Get-Date).AddSeconds($MaxWaitSec)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  $s = & $probe
  if ($s.ok) { Write-Output ("STARTED " + $s.dev.name + " vram_free=" + $s.dev.vram_free); exit 0 }
}
Write-Output 'STILL_STARTING'
Write-Output '--- err tail ---'
Get-Content 'C:\chatbox_temp\comfyui_run\comfy.out.log' -Tail 8
exit 2
