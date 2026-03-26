$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $projectRoot "powershell_utf8.ps1")

$pythonExe = Join-Path $projectRoot ".venv\\Scripts\\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

Set-Location $projectRoot
& $pythonExe "ivvx.py"
