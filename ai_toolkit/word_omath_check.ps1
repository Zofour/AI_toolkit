$ErrorActionPreference = 'Stop'

# usage: powershell -File word_omath_check.ps1 <docx absolute path>
# output: oMaths=<native formula count> / pages=<page count>
# on bad file: error=<reason> (does NOT hang on Word repair dialog)

if ($args.Count -lt 1 -or [string]::IsNullOrWhiteSpace($args[0])) {
    Write-Output 'usage: word_omath_check.ps1 <docx absolute path>'
    exit 2
}
$path = $args[0]
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    Write-Output ("error=not_found: " + $path)
    exit 3
}

$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0          # wdAlertsNone: suppress repair dialog (would hang otherwise)
try { $w.AutomationSecurity = 3 } catch {}   # msoAutomationSecurityForceDisable

$d = $null
try {
    $d = $w.Documents.Open($path, $false, $true)
    Write-Output ("oMaths=" + $d.OMaths.Count)
    Write-Output ("pages=" + $d.ComputeStatistics(2))
}
catch {
    Write-Output ("error=" + $_.Exception.Message)
    exit 1
}
finally {
    if ($d -ne $null) { try { $d.Close($false) } catch {} }
    try { $w.Quit() } catch {}
    try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($w) } catch {}
}
