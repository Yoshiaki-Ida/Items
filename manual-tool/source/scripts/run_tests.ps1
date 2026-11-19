$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path (Join-Path $ProjectRoot ".venv") "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

Push-Location $ProjectRoot
try {
    & $Python -m pytest
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
