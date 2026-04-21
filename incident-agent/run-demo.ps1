param(
    [switch]$NoBuild,
    [switch]$Detached
)

$ErrorActionPreference = "Stop"

Write-Host "Starting Incident Agent demo stack for Windows..." -ForegroundColor Cyan

try {
    docker version | Out-Null
} catch {
    Write-Host "Docker is not available. Start Docker Desktop first." -ForegroundColor Red
    exit 1
}

# Ensure profiled services (including simulator) are fully removed so stale
# network IDs cannot be reused from previous runs.
Write-Host "Cleaning previous compose stack (profile-aware)..." -ForegroundColor Yellow
docker compose --profile simulator down --remove-orphans | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker-compose --profile simulator down --remove-orphans | Out-Null
}

$composeArgs = @("--profile", "simulator", "up")
if (-not $NoBuild) {
    $composeArgs += "--build"
}
if ($Detached) {
    $composeArgs += "-d"
}

Write-Host "Running: docker compose $($composeArgs -join ' ')" -ForegroundColor Yellow
docker compose @composeArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to start with 'docker compose'. Trying 'docker-compose'..." -ForegroundColor Yellow
    $legacyArgs = @("--profile", "simulator", "up")
    if (-not $NoBuild) {
        $legacyArgs += "--build"
    }
    if ($Detached) {
        $legacyArgs += "-d"
    }
    docker-compose @legacyArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Unable to start the demo stack." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if ($Detached) {
    Write-Host "Demo stack started in background." -ForegroundColor Green
    Write-Host "Open: http://localhost:8002" -ForegroundColor Green
    Write-Host "Use .\stop-demo.ps1 to stop it." -ForegroundColor Cyan
}
