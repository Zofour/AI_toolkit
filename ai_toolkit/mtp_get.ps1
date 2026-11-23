param(
  [Parameter(Mandatory=$true)][string]$RemoteDir,   # e.g. /sdcard/output
  [Parameter(Mandatory=$true)][string]$Pattern,     # e.g. zotest_*.jpg
  [Parameter(Mandatory=$true)][string]$DestDir
)
$ErrorActionPreference='Stop'
if(-not (Test-Path $DestDir)){ New-Item -ItemType Directory -Force -Path $DestDir | Out-Null }
$sh = New-Object -ComObject Shell.Application
$pc = $sh.NameSpace(17)
$dev = $pc.Items() | Where-Object { $_.Name -eq 'CanMV' } | Select-Object -First 1
if(-not $dev){ Write-Output 'NO_DEVICE'; exit 2 }
$cur = $dev.GetFolder
$parts = $RemoteDir.Trim('/').Split('/')
foreach($p in $parts){
  if($p -eq ''){ continue }
  $nx = $cur.Items() | Where-Object { $_.Name -eq $p } | Select-Object -First 1
  if(-not $nx){ Write-Output ('NO_DIR:'+$p); exit 3 }
  $cur = $nx.GetFolder
}
$df = $sh.NameSpace($DestDir)
$wild = $Pattern -replace '\*','.*' -replace '\?','.'
$wild = '^' + $wild + '$'
$n = 0
foreach($it in $cur.Items()){
  if($it.Name -match $wild){ $df.CopyHere($it, 16); $n++ }
}
Start-Sleep -Milliseconds 2500
Write-Output ("copied=" + $n)
Get-ChildItem -Path $DestDir -Filter $Pattern | ForEach-Object { Write-Output ($_.Name + ' ' + $_.Length) }
