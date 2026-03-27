$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $projectRoot "powershell_utf8.ps1")

$pythonExe = Join-Path $projectRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Set-Location $projectRoot
$backfillStart = (Get-Date -Date (Get-Date).AddMonths(-3) -Format "yyyy-MM-01")
$backfillEnd = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
& $pythonExe "app.py" "sync-all"
& $pythonExe "app.py" "backfill-1000-sina" "--start-date" $backfillStart "--end-date" $backfillEnd
& $pythonExe "app.py" "refresh-realtime-dual" "--months-ahead-50" "4" "--months-ahead-1000" "4"
& $pythonExe "generate_ivix_sse_chart.py"
