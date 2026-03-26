$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $projectRoot "powershell_utf8.ps1")

$codexCmd = "D:\\codex\\codex.cmd"
if (-not (Test-Path $codexCmd)) {
    throw "Codex launcher not found: $codexCmd"
}

& $codexCmd @args
exit $LASTEXITCODE
