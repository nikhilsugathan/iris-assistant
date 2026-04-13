# IRIS v4.8.3 Model Warmup Script
# Optimized for RTX 5050 (8GB VRAM)

$OllamaUrl = "http://localhost:11434/api/generate"
$Models = @("llama3.2:3b", "qwen2.5:7b")

Write-Host "→ Initializing Aletheia High-Performance Tier..." -ForegroundColor Cyan

foreach ($Model in $Models) {
    Write-Host "  → Pre-loading $Model into VRAM..." -ForegroundColor White
    
    # Payload: empty prompt with 'keep_alive' set to 24 hours
    $Payload = @{
        model = $Model
        prompt = ""
        keep_alive = "24h"
    } | ConvertTo-Json

    try {
        Invoke-RestMethod -Uri $OllamaUrl -Method Post -Body $Payload -ContentType "application/json" -ErrorAction Stop > $null
        Write-Host "    ✓ $Model Loaded." -ForegroundColor Green
    }
    catch {
        Write-Host "    ✗ Failed to load $Model. Is Ollama running?" -ForegroundColor Red
    }
}

Write-Host "`n[IRIS]: Models are warm. Zero-latency mode active." -ForegroundColor BoldCyan