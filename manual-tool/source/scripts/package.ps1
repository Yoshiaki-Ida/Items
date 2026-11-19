$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PackageRoot = Join-Path $ProjectRoot "dist\ManualTool"
$ZipPath = Join-Path $ProjectRoot "dist\ManualTool-windows.zip"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

& $Python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in the workspace virtual environment."
}


& $Python -m PyInstaller --noconfirm --distpath (Join-Path $ProjectRoot "dist") --workpath (Join-Path $ProjectRoot "build") (Join-Path $ProjectRoot "ManualTool.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$Launcher = @'
@echo off
setlocal
set "APP_DIR=%~dp0"
start "ManualTool" "%APP_DIR%ManualTool.exe" web
start "" http://127.0.0.1:8765/
endlocal
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "ManualTool.bat") -Value $Launcher -Encoding ascii

Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Setup-PlantUML.ps1") -Destination $PackageRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\DISTRIBUTION_README.txt") -Destination (Join-Path $PackageRoot "README.txt") -Force

$GuideRoot = Join-Path $PackageRoot "docs"
New-Item -ItemType Directory -Path $GuideRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\USER_GUIDE.html") -Destination $GuideRoot -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\USER_GUIDE_EMBEDDED.html") -Destination $GuideRoot -Force
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "docs") -Filter "*.png" -File | Copy-Item -Destination $GuideRoot -Force

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Host "Package created: $ZipPath"