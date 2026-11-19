$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '_internal/runtime/plantuml'
$javaHome = Join-Path $runtime 'java'
$java = Join-Path $javaHome 'bin/java.exe'
if (Test-Path -LiteralPath $java -PathType Leaf) {
    Write-Host 'PlantUML Java runtime is already installed.'
    exit 0
}
if (-not (Test-Path -LiteralPath (Join-Path $runtime 'plantuml.jar') -PathType Leaf)) {
    throw 'The ManualTool distribution folder is incomplete.'
}
if (Test-Path -LiteralPath $javaHome) {
    throw 'A Java folder already exists without java.exe. Check it before retrying.'
}

$archiveName = 'zulu21.54.201-ca-jre21.0.13.1-win_x64.zip'
$url = 'https://cdn.azul.com/zulu/bin/' + $archiveName
$expected = '888995F738298E22C34C3E4BF72230573360E4B63A19455EC76C0BF59235A972'
$stage = Join-Path $runtime ('.java-setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    $archive = Join-Path $stage $archiveName
    $extract = Join-Path $stage 'extract'
    Write-Host 'Downloading the Java runtime from Azul.'
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) {
        throw 'The Java archive checksum did not match.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $extract
    $package = Join-Path $extract ([IO.Path]::GetFileNameWithoutExtension($archiveName))
    if (-not (Test-Path -LiteralPath (Join-Path $package 'bin/java.exe') -PathType Leaf)) {
        throw 'The Java archive did not contain the expected runtime.'
    }
    [IO.Directory]::Move($package, $javaHome)
    Write-Host 'PlantUML Java runtime installed. Start ManualTool.bat.'
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
