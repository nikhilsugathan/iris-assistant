param(
    [string]$Request = "",
    [string]$Response = "",
    [ValidateSet("once", "bootstrap", "watch")]
    [string]$Workflow = "once",
    [ValidateSet("auto", "api", "web")]
    [string]$Mode = "auto",
    [ValidateSet("auto", "msedge", "chrome", "chromium")]
    [string]$BrowserChannel = "auto",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Request) {
    $Request = Join-Path $ScriptDir "..\ai-collab\claude-bridge-request.md"
}

if (-not $Response) {
    $Response = Join-Path $ScriptDir "..\ai-collab\claude-bridge-response.md"
}

Write-Host ""
Write-Host "IRIS Claude Bridge" -ForegroundColor Cyan
Write-Host "Workflow: $Workflow"
Write-Host "Mode    : $Mode"
Write-Host "Browser : $BrowserChannel"
Write-Host "Request : $Request"
Write-Host "Response: $Response"
Write-Host ""

$bridgeArgs = @(
    (Join-Path $ScriptDir "claude_bridge.py"),
    "--workflow", $Workflow,
    "--mode", $Mode,
    "--browser-channel", $BrowserChannel,
    "--request", $Request,
    "--response", $Response
)

if ($ExtraArgs) {
    $bridgeArgs += $ExtraArgs
}

py -3 @bridgeArgs
