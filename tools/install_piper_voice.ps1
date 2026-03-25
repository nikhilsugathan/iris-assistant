param(
    [string]$Voice = "en_GB-alan-medium",
    [string]$DownloadDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $DownloadDir) {
    $DownloadDir = Join-Path (Join-Path $PSScriptRoot "..") "build\piper"
}

$ResolvedDir = [System.IO.Path]::GetFullPath($DownloadDir)
New-Item -ItemType Directory -Force -Path $ResolvedDir | Out-Null

python -c "from pathlib import Path; from piper.download_voices import download_voice; import sys; voice=sys.argv[1]; download_dir=Path(sys.argv[2]); download_dir.mkdir(parents=True, exist_ok=True); download_voice(voice, download_dir); print(download_dir / f'{voice}.onnx')" "$Voice" "$ResolvedDir"

Write-Host ""
Write-Host "Piper voice download complete." -ForegroundColor Green
Write-Host "Voice: $Voice"
Write-Host "Directory: $ResolvedDir"
Write-Host ""
Write-Host "IRIS will auto-detect this voice from build\\piper while Piper TTS is enabled."
