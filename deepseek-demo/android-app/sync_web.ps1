# Copy the web build output into the APK assets/www folder.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path (Split-Path -Parent $root) 'dist'
$www = Join-Path $root 'app\src\main\assets\www'

if (-not (Test-Path $dist)) {
    throw "missing dist: $dist  (run: npx rspack build -c rspack.config.ts)"
}
if (Test-Path $www) { Remove-Item $www -Recurse -Force }
New-Item -ItemType Directory -Path $www -Force | Out-Null
Copy-Item -Path (Join-Path $dist '*') -Destination $www -Recurse -Force
$count = (Get-ChildItem $www -Recurse -File | Measure-Object).Count
$size = '{0:N1} MB' -f ((Get-ChildItem $www -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "synced: $count files, $size -> $www"
