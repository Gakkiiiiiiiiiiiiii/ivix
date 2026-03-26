$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

# Windows PowerShell 5.1 treats BOM-less UTF-8 files as ANSI unless Encoding is explicit.
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$utf8Cmdlets = @(
    "Get-Content",
    "Select-String",
    "Import-Csv",
    "Export-Csv",
    "Set-Content",
    "Add-Content",
    "Out-File"
)

foreach ($cmdlet in $utf8Cmdlets) {
    $PSDefaultParameterValues[("{0}:Encoding" -f $cmdlet)] = "utf8"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
