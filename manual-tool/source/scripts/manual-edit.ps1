$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path (Join-Path $ProjectRoot ".venv") "Scripts\python.exe"
$EntryPoint = Join-Path $ProjectRoot "main.py"
$Port = 8765

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($null -ne $Listener) {
    $RunningProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($Listener.OwningProcess)"
    $CommandLine = $RunningProcess.CommandLine
    $UsesProjectPython = $null -ne $CommandLine -and
        $CommandLine.IndexOf($Python, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    $UsesManualToolEntryPoint = $null -ne $CommandLine -and (
        $CommandLine.IndexOf($EntryPoint, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $CommandLine -match '(?:^|[\s"])main\.py"?\s+web(?:\s|$)'
    )
    $IsManualTool = $UsesProjectPython -and $UsesManualToolEntryPoint
    if (-not $IsManualTool) {
        throw "Port $Port is already used by another application (PID $($Listener.OwningProcess))."
    }

    Write-Host "Restarting the existing ManualTool server (PID $($Listener.OwningProcess))..."
    Stop-Process -Id $Listener.OwningProcess
    for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
        if ($null -eq (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            break
        }
        Start-Sleep -Milliseconds 100
    }
}

Start-Process "http://127.0.0.1:$Port"
& $Python $EntryPoint web
exit $LASTEXITCODE