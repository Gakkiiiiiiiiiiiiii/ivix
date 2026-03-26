$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $projectRoot "powershell_utf8.ps1")

$venvPath = Join-Path $projectRoot ".venv"
$scriptsPath = Join-Path $venvPath "Scripts"

$env:VIRTUAL_ENV = $venvPath
if (-not ($env:PATH -split ';' | Where-Object { $_ -eq $scriptsPath })) {
    $env:PATH = "$scriptsPath;$env:PATH"
}

Set-Location $projectRoot
Write-Host "Activated ivix environment (UTF-8): $venvPath"
