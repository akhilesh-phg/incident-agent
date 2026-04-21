$ErrorActionPreference = "Stop"

Write-Host "Stopping Incident Agent demo stack..." -ForegroundColor Cyan

docker compose --profile simulator down --remove-orphans
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fallback: trying docker-compose down..." -ForegroundColor Yellow
    docker-compose --profile simulator down --remove-orphans
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Unable to stop demo stack cleanly." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host "Demo stack stopped." -ForegroundColor Green
