param(
    [string]$TranscriptPath = (Join-Path $PSScriptRoot "..\ai-collab\transcript.md"),
    [int]$Tail = 30,
    [switch]$OpenInVSCode,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"

try {
    $resolvedPath = Resolve-Path -Path $TranscriptPath
} catch {
    Write-Host "Transcript not found: $TranscriptPath" -ForegroundColor Red
    Write-Host "Expected file: D:\IRIS\ai-collab\transcript.md" -ForegroundColor Yellow
    exit 1
}

$transcriptFile = $resolvedPath.Path

Write-Host ""
Write-Host "IRIS AI Transcript Watcher" -ForegroundColor Cyan
Write-Host "File: $transcriptFile"
Write-Host "Showing last $Tail lines, then waiting for new entries..."
Write-Host "Press Ctrl+C to stop."
Write-Host ""

if ($OpenInVSCode) {
    $codeCommand = Get-Command code -ErrorAction SilentlyContinue
    if ($codeCommand) {
        Start-Process -FilePath $codeCommand.Source -ArgumentList @("-r", $transcriptFile) | Out-Null
    } else {
        Write-Host "VS Code command 'code' was not found. Skipping editor launch." -ForegroundColor Yellow
        Write-Host ""
    }
}

Get-Content -Path $transcriptFile -Tail $Tail

if (-not $NoWait) {
    Get-Content -Path $transcriptFile -Tail 0 -Wait
}
