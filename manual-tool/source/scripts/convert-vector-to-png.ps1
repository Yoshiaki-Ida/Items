param(
    [Parameter(Mandatory = $true)][string]$InputDirectory,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$inputRoot = (Resolve-Path -LiteralPath $InputDirectory).Path
$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($outputRoot) | Out-Null
$application = $null
try {
    $application = New-Object -ComObject Visio.Application
    $application.Visible = $false
    $application.AlertResponse = 7
    foreach ($source in Get-ChildItem -LiteralPath $inputRoot -File | Where-Object { $_.Extension -in ".vsd", ".vsdx", ".emf", ".wmf" }) {
        $document = $null
        try {
            # Read-only + hidden + excluded from recent-file list + macros disabled.
            $document = $application.Documents.OpenEx($source.FullName, 202)
            $page = $document.Pages.Item(1)
            $target = Join-Path $outputRoot ($source.BaseName + ".png")
            $page.Export($target)
        }
        catch {
            Write-Warning ("PNG conversion failed for {0}: {1}" -f $source.Name, $_.Exception.Message)
        }
        finally {
            if ($null -ne $document) {
                $document.Close()
                [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
            }
        }
    }
}
finally {
    if ($null -ne $application) {
        $application.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($application)
    }
}
