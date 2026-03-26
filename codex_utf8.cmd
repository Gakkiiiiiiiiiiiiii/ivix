@echo off
setlocal
powershell.exe -NoLogo -ExecutionPolicy Bypass -File "%~dp0launch_codex_utf8.ps1" %*
