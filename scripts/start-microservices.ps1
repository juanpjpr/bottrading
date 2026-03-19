param(
    [int]$BasePort = 8010,
    [switch]$WithWeb
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$serviceDirs = Get-ChildItem -Path (Join-Path $repoRoot "services") -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "app.py") } |
    Sort-Object Name

if (-not $serviceDirs) {
    Write-Host "No se encontraron microservicios en services/ con app.py" -ForegroundColor Yellow
    exit 0
}

$knownPorts = @{
    "execution_service" = 8010
    "market_data_service" = 8020
    "ai_filter_service"   = 8030
    "signal_engine"       = 8040
    "news_service"        = 8050
}

$assignedPorts = @{}
$nextDynamicPort = $BasePort

foreach ($serviceDir in $serviceDirs) {
    $serviceName = $serviceDir.Name

    if ($knownPorts.ContainsKey($serviceName)) {
        $assignedPorts[$serviceName] = $knownPorts[$serviceName]
        continue
    }

    while ($assignedPorts.Values -contains $nextDynamicPort) {
        $nextDynamicPort += 10
    }

    $assignedPorts[$serviceName] = $nextDynamicPort
    $nextDynamicPort += 10
}

$launched = @()

foreach ($serviceDir in $serviceDirs) {
    $serviceName = $serviceDir.Name
    $port = $assignedPorts[$serviceName]
    $module = "services.$serviceName.app:app"
    $command = "Set-Location '$repoRoot'; python -m uvicorn $module --reload --port $port"

    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        $command
    ) | Out-Null

    $launched += [pscustomobject]@{
        Service = $serviceName
        Port    = $port
        Url     = "http://127.0.0.1:$port"
    }
}

if ($WithWeb) {
    $webCommand = "Set-Location '$repoRoot'; python -m uvicorn bot_trading_news.service:app --reload --port 8000"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        $webCommand
    ) | Out-Null

    $launched += [pscustomobject]@{
        Service = "dashboard_web"
        Port    = 8000
        Url     = "http://127.0.0.1:8000"
    }
}

Write-Host ""
Write-Host "Servicios lanzados" -ForegroundColor Cyan
$launched | Sort-Object Port | Format-Table -AutoSize

Write-Host ""
Write-Host "Tip:" -ForegroundColor DarkCyan
Write-Host "Agrega EXECUTION_SERVICE_URL=http://127.0.0.1:8010 en .env para que la web use el execution_service."
Write-Host "Tambien podes agregar NEWS_SERVICE_URL=http://127.0.0.1:8050, AI_FILTER_SERVICE_URL=http://127.0.0.1:8030, MARKET_DATA_SERVICE_URL=http://127.0.0.1:8020 y SIGNAL_ENGINE_URL=http://127.0.0.1:8040."
