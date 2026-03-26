# AGENTS.md

## Windows PowerShell UTF-8

- On Windows PowerShell 5.1, never use plain `Get-Content`, `Select-String`, or `Import-Csv` for UTF-8 source files.
- Always pass `-Encoding UTF8` explicitly when using PowerShell file-reading cmdlets.
- Prefer `rg`, `rg --files`, or `Get-Content -Encoding UTF8` when inspecting project files.
- If output looks like mojibake, retry with explicit UTF-8 before assuming the file is corrupted.
- When launching Python from PowerShell and Chinese output matters, ensure `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`.
