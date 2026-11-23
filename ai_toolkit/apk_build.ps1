<#
.SYNOPSIS
    One-stop Android APK build/probe helper for THIS machine (Windows 11).
    Reuses the already-installed portable JDK17 + local Android SDK + cached Gradle 8.13.

.DESCRIPTION
    Environment on this box (verified 2026-10-20):
      JDK17      : C:\chatbox_temp\chatbox-bridge\tools\jdk17   (Temurin 17.0.20.1, preferred)
                   C:\chatbox_temp\jdk17\jdk-17.0.20.1+1      (backup copy, identical build)
      Android SDK: %LOCALAPPDATA%\Android\Sdk
                   platforms android-36 | build-tools 35.0.0, 36.1.0 | platform-tools(adb) | emulator
                   NO cmdline-tools (no sdkmanager), NO ndk, NO AVD
      Gradle     : 8.13 cached in %USERPROFILE%\.gradle\wrapper\dists\gradle-8.13-bin\...
      System java: Oracle JRE 8 -> ALWAYS set JAVA_HOME explicitly, never rely on PATH java.

.EXAMPLES
    powershell -File apk_build.ps1 -Probe
    powershell -File apk_build.ps1 -Project C:\chatbox_temp\chatbox-bridge\android
    powershell -File apk_build.ps1 -Project C:\chatbox_temp\ai-gen-studio\android -Install
    powershell -File apk_build.ps1 -Project <dir> -Task help      # fast config sanity check
    powershell -File apk_build.ps1 -Project <dir> -Variant release -Clean
#>
[CmdletBinding()]
param(
    [string]$Project = "",
    [ValidateSet("debug", "release", "both")][string]$Variant = "debug",
    [string]$Task = "",
    [switch]$Probe,
    [switch]$Deep,          # probe: also launch gradle to print its banner (slower)
    [switch]$Json,
    [switch]$Adb,           # probe: also query adb devices (can block while starting the server)
    [switch]$Clean,
    [switch]$Install,
    [switch]$Offline,
    [switch]$NoDaemon,      # recommended for agent/CI: daemon otherwise keeps stdout open and hangs the caller
    [switch]$NoEnvWrite
)

$ErrorActionPreference = "Stop"

# Native tools (java/gradle/adb) write banners to stderr; with Stop that aborts the script.
# Always go through this wrapper instead of calling & directly.
function Invoke-Native {
    param([string]$Exe, [string[]]$ArgList = @(), [int]$TimeoutSec = 15)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $Exe
    $psi.Arguments              = ((@($ArgList) | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.RedirectStandardInput  = $true
    $psi.CreateNoWindow         = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    try {
        [void]$p.Start()
        $outTask = $p.StandardOutput.ReadToEndAsync()
        $errTask = $p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit($TimeoutSec * 1000)) {
            try { $p.Kill() } catch {}
            return @("<<TIMEOUT ${TimeoutSec}s: $Exe $($psi.Arguments)>>")
        }
        $all = @()
        $so = $outTask.Result; $se = $errTask.Result
        if ($so) { $all += ($so -split "`r?`n" | Where-Object { $_ -ne "" }) }
        if ($se) { $all += ($se -split "`r?`n" | Where-Object { $_ -ne "" }) }
        return $all
    } catch {
        return @("<<ERROR: $($_.Exception.Message)>>")
    } finally {
        $p.Dispose()
    }
}

# ---------------------------------------------------------------- constants
$JDK_CANDIDATES = @(
    "C:\chatbox_temp\chatbox-bridge\tools\jdk17",
    "C:\chatbox_temp\jdk17\jdk-17.0.20.1+1"
)
$SDK_DIR       = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$GRADLE_DISTS  = Join-Path $env:USERPROFILE ".gradle\wrapper\dists"

function Get-JdkDir {
    foreach ($d in $JDK_CANDIDATES) {
        if (Test-Path (Join-Path $d "bin\javac.exe")) { return $d }
    }
    return $null
}

function Get-GradleLauncher {
    param([string]$Proj)
    if ($Proj) {
        $w = Join-Path $Proj "gradlew.bat"
        if (Test-Path $w) { return $w }
    }
    # fall back to a cached distribution (projects without a wrapper, e.g. ai-gen-studio\android)
    $hits = Get-ChildItem $GRADLE_DISTS -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Get-ChildItem $_.FullName -Recurse -Filter "gradle.bat" -ErrorAction SilentlyContinue } |
            Where-Object { $_.FullName -match "\\bin\\gradle\.bat$" }
    if ($hits) { return ($hits | Select-Object -First 1).FullName }
    return $null
}

function Get-SdkInfo {
    $info = [ordered]@{
        sdk_dir       = $SDK_DIR
        exists        = (Test-Path $SDK_DIR)
        platforms     = @()
        build_tools   = @()
        platform_tools = (Test-Path (Join-Path $SDK_DIR "platform-tools\adb.exe"))
        emulator      = (Test-Path (Join-Path $SDK_DIR "emulator\emulator.exe"))
        cmdline_tools = (Test-Path (Join-Path $SDK_DIR "cmdline-tools"))
        ndk           = @()
        licenses      = @()
    }
    foreach ($k in @("platforms", "build-tools", "ndk", "licenses")) {
        $p = Join-Path $SDK_DIR $k
        $key = $k -replace "-", "_"
        if (Test-Path $p) {
            $items = @(Get-ChildItem $p -Directory -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
            if ($items.Count -eq 0) {
                $items = @(Get-ChildItem $p -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
            }
            $info[$key] = $items
        }
    }
    return $info
}

function Write-Probe {
    $jdk = Get-JdkDir
    $sdk = Get-SdkInfo
    $g   = Get-GradleLauncher ""
    $gv  = $null
    $gVer = if ($g -match 'gradle-([0-9][^\\]*)') { "gradle " + ($Matches[1] -replace '-bin$','') } else { $null }
    if ($g -and $Deep) {
        $gjv = Invoke-Native $g @("--version", "--console=plain") 20
        $hit = ($gjv | Select-String '^Gradle ' | Select-Object -First 1)
        if ($hit) { $gv = $hit.ToString() }
    }
    if (-not $gv) { $gv = $gVer }

    if ($Json) {
        $out = [ordered]@{
            java_home        = $jdk
            java_version     = if ($jdk) { (Invoke-Native (Join-Path $jdk "bin\javac.exe") @("-version")) -join " " } else { $null }
            system_java      = (Invoke-Native "java" @("-version"))[0]
            sdk              = $sdk
            gradle_launcher  = $g
            gradle_version   = $gv
            avd_dir          = (Test-Path (Join-Path $env:USERPROFILE ".android\avd"))
            adb_devices      = if ($sdk.platform_tools -and $Adb) { Invoke-Native (Join-Path $SDK_DIR "platform-tools\adb.exe") @("devices") 20 } else { @("(skipped: pass -Adb)") }
        }
        $out | ConvertTo-Json -Depth 5
        return
    }

    Write-Host "=== APK BUILD ENVIRONMENT (this machine) ===" -ForegroundColor Cyan
    Write-Host ("JDK17 (JAVA_HOME) : {0}" -f $(if ($jdk) { $jdk } else { "!! MISSING !!" })) -ForegroundColor $(if ($jdk) { "Green" } else { "Red" })
    if ($jdk) { Write-Host ("  javac           : {0}" -f ((Invoke-Native (Join-Path $jdk "bin\javac.exe") @("-version")) -join " ")) }
    Write-Host ("System java on PATH: {0}" -f ((Invoke-Native "java" @("-version"))[0])) -ForegroundColor DarkYellow
    Write-Host "  ^ Oracle JRE 8 - do NOT build with it; always pin JAVA_HOME." -ForegroundColor DarkYellow

    Write-Host ("`nAndroid SDK       : {0}" -f $SDK_DIR) -ForegroundColor $(if ($sdk.exists) { "Green" } else { "Red" })
    Write-Host ("  platforms       : {0}" -f ($(if ($sdk.platforms) { $sdk.platforms -join ", " } else { "(none)" })))
    Write-Host ("  build-tools     : {0}" -f ($(if ($sdk.build_tools) { $sdk.build_tools -join ", " } else { "(none)" })))
    Write-Host ("  platform-tools  : {0}" -f $sdk.platform_tools)
    Write-Host ("  emulator        : {0}" -f $sdk.emulator)
    Write-Host ("  cmdline-tools   : {0}" -f $sdk.cmdline_tools) -ForegroundColor $(if ($sdk.cmdline_tools) { "Green" } else { "DarkYellow" })
    Write-Host ("  ndk             : {0}" -f ($(if ($sdk.ndk) { $sdk.ndk -join ", " } else { "(none)" })))
    Write-Host ("  licenses        : {0}" -f ($(if ($sdk.licenses) { $sdk.licenses -join ", " } else { "(none)" })))
    Write-Host ("  AVD dir         : {0}" -f (Test-Path (Join-Path $env:USERPROFILE ".android\avd")))

    Write-Host ("`nGradle           : {0}" -f $(if ($g) { $g } else { "!! MISSING !!" })) -ForegroundColor $(if ($g) { "Green" } else { "Red" })
    if ($gv) { Write-Host ("  {0}" -f $gv) }

    if ($sdk.platform_tools) {
        Write-Host "`nadb devices:" -ForegroundColor Cyan
        if ($Adb) {
            Invoke-Native (Join-Path $SDK_DIR "platform-tools\adb.exe") @("devices") 20 | ForEach-Object { Write-Host "  $_" }
        } else {
            Write-Host "  (skipped - pass -Adb to query; adb can block while starting its server)" -ForegroundColor DarkGray
        }
    }
    Write-Host "`nProjects with a wrapper: C:\chatbox_temp\chatbox-bridge\android"
    Write-Host "Projects WITHOUT wrapper (script uses cached gradle): C:\chatbox_temp\ai-gen-studio\android"
}

function Set-BuildEnv {
    param([string]$Jdk)
    $env:JAVA_HOME        = $Jdk
    $env:ANDROID_HOME     = $SDK_DIR
    $env:ANDROID_SDK_ROOT = $SDK_DIR
    $env:GRADLE_USER_HOME = Join-Path $env:USERPROFILE ".gradle"
    $pre = @(
        (Join-Path $Jdk "bin"),
        (Join-Path $SDK_DIR "platform-tools")
    ) | Where-Object { Test-Path $_ }
    $env:Path = ($pre -join ";") + ";" + $env:Path
}

function Ensure-LocalProperties {
    param([string]$Proj)
    $lp = Join-Path $Proj "local.properties"
    $sdkForward = $SDK_DIR -replace '\\', '/'
    $want = "sdk.dir=$sdkForward"
    if (Test-Path $lp) {
        $cur = Get-Content $lp -Raw
        if ($cur -notmatch "(?m)^\s*sdk\.dir\s*=") {
            Add-Content -Path $lp -Value "`r`n$want" -Encoding ASCII
            Write-Host "[env] local.properties: appended sdk.dir" -ForegroundColor DarkGray
        }
    } else {
        Set-Content -Path $lp -Value $want -Encoding ASCII
        Write-Host "[env] local.properties: created" -ForegroundColor DarkGray
    }
}

function Get-Apks {
    param([string]$Proj)
    Get-ChildItem $Proj -Recurse -Filter "*.apk" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\outputs\\apk\\" } |
        Sort-Object LastWriteTime -Descending
}

# ---------------------------------------------------------------- main
if ($Probe -or -not $Project) { Write-Probe; if (-not $Project) { return } }

$Proj = (Resolve-Path $Project).Path
if (-not (Test-Path (Join-Path $Proj "settings.gradle.kts")) -and -not (Test-Path (Join-Path $Proj "settings.gradle"))) {
    throw "Not a Gradle project root (no settings.gradle[.kts]): $Proj"
}

$jdk = Get-JdkDir
if (-not $jdk) { throw "Portable JDK17 not found. Checked: $($JDK_CANDIDATES -join ' ; ')" }
$launcher = Get-GradleLauncher $Proj
if (-not $launcher) { throw "No gradlew.bat in project and no cached Gradle dist under $GRADLE_DISTS" }

if (-not $NoEnvWrite) {
    Set-BuildEnv $jdk
    Ensure-LocalProperties $Proj
}

$gp = Join-Path $Proj "gradle.properties"
if (Test-Path $gp) {
    $hit = Select-String -Path $gp -Pattern "^\s*org\.gradle\.java\.home\s*=\s*(.+)$" -ErrorAction SilentlyContinue
    if ($hit) {
        $declared = $hit.Matches[0].Groups[1].Value.Trim()
        if (-not (Test-Path (Join-Path $declared "bin\java.exe"))) {
            Write-Host "[warn] gradle.properties org.gradle.java.home points to a missing JDK: $declared" -ForegroundColor Yellow
            Write-Host "[warn] fix it or remove that line (env JAVA_HOME=$jdk is used instead)" -ForegroundColor Yellow
        }
    }
}

Write-Host "project : $Proj"
Write-Host "jdk     : $jdk"
Write-Host "sdk     : $SDK_DIR"
Write-Host "gradle  : $launcher"
Write-Host ""

$tasks = @()
if ($Task) { $tasks = @($Task) }
else {
    if ($Variant -eq "both") { $tasks = @("assembleDebug", "assembleRelease") }
    else { $tasks = @("assemble" + ($Variant.Substring(0,1).ToUpper() + $Variant.Substring(1))) }
}
if ($Clean) { $tasks = @("clean") + $tasks }

$gradleArgs = @()
$gradleArgs += $tasks
$gradleArgs += "--console=plain"
$gradleArgs += "--stacktrace"
if ($Offline)   { $gradleArgs += "--offline" }
if ($NoDaemon)  { $gradleArgs += "--no-daemon" }

$sw = [Diagnostics.Stopwatch]::StartNew()
Push-Location $Proj
try {
    # NOTE: never wrap gradle in Start-Process with -RedirectStandardOutput (hangs the agent).
    & $launcher @gradleArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
$sw.Stop()

if ($code -ne 0) {
    Write-Host "`nBUILD FAILED (exit $code) after $([math]::Round($sw.Elapsed.TotalSeconds,1))s" -ForegroundColor Red
    exit $code
}

$apks = Get-Apks $Proj
if (-not $apks) {
    Write-Host "`nBuild OK but no APK found under **\outputs\apk\" -ForegroundColor Yellow
    exit 0
}
Write-Host "`nBUILD OK in $([math]::Round($sw.Elapsed.TotalSeconds,1))s" -ForegroundColor Green
foreach ($a in $apks) {
    Write-Host ("APK: {0}  ({1:N1} MB, {2})" -f $a.FullName, ($a.Length / 1MB), $a.LastWriteTime)
}

if ($Install) {
    $adb = Join-Path $SDK_DIR "platform-tools\adb.exe"
    $dev = (Invoke-Native $adb @("devices") | Select-String "\sdevice$")
    if (-not $dev) { Write-Host "adb: no device/emulator attached - skip install" -ForegroundColor Yellow; exit 0 }
    $apk = $apks | Where-Object { $_.Name -match $Variant } | Select-Object -First 1
    if (-not $apk) { $apk = $apks[0] }
    Write-Host "adb install -r $($apk.FullName)"
    & $adb install -r $apk.FullName
}
