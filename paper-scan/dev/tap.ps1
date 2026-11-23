param(
  [string]$Text,
  [string]$Prefix = "false"
)
# 按屏幕文字点击：dump UI 找到节点 bounds 的中心点后 input tap
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb shell uiautomator dump /sdcard/u.xml 2>&1 | Out-Null
$raw = (& $adb shell cat /sdcard/u.xml 2>&1) -join "`n"
if (-not $raw) { Write-Output "dump failed"; exit 1 }
$nodes = [regex]::Matches($raw, '<node[^>]*text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
$hit = $null
foreach ($n in $nodes) {
  $t = $n.Groups[1].Value
  if (($Prefix -eq "true" -and $t.StartsWith($Text) -and $t.Length -gt 0) -or $t -eq $Text) {
    $hit = $n; break
  }
}
if (-not $hit) {
  Write-Output "not found: $Text"
  $nodes | ForEach-Object { if ($_.Groups[1].Value.Length -gt 0) { Write-Output ("  text=" + $_.Groups[1].Value + " " + $_.Groups[2].Value + "," + $_.Groups[3].Value + "," + $_.Groups[4].Value + "," + $_.Groups[5].Value) } } | Select-Object -First 25
  exit 2
}
$x1 = [int]$hit.Groups[2].Value; $y1 = [int]$hit.Groups[3].Value
$x2 = [int]$hit.Groups[4].Value; $y2 = [int]$hit.Groups[5].Value
$cx = [int](($x1 + $x2) / 2); $cy = [int](($y1 + $y2) / 2)
& $adb shell input tap $cx $cy | Out-Null
Write-Output ("tapped '" + $hit.Groups[1].Value + "' at " + $cx + "," + $cy)
