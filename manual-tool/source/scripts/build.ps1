$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path (Join-Path $ProjectRoot ".venv") "Scripts\python.exe"
$Utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $Utf8
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

& $Python (Join-Path $ProjectRoot "main.py") build @args
exit $LASTEXITCODE
