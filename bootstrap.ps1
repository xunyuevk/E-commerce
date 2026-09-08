<#
.SYNOPSIS
    One-click bootstrap script for ShopMind P2 Demo
.DESCRIPTION
    This script assumes a fresh clone or new machine.
    1. Check .env, copy from .env.example if missing
    2. docker compose up -d
    3. Poll for all 4 services (mysql/elasticsearch/redis/minio) to become healthy (90s timeout)
    4. Run: doctor -> p1 run -> p2 ingest -> p2 demo
    5. Exit with non-zero code on any failure
#>

$ErrorActionPreference = "Continue"

$services = @("mysql", "elasticsearch", "redis", "minio")

Write-Host "`n[1/5] Checking environment file..." -ForegroundColor Cyan
if (Test-Path .env) {
    Write-Host "  .env exists, keeping existing configuration" -ForegroundColor Green
} else {
    if (Test-Path .env.example) {
        Copy-Item .env.example .env
        Write-Host "  .env.example copied to .env" -ForegroundColor Green
    } else {
        Write-Host "  ERROR: .env.example not found" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n[2/5] Starting containers (docker compose up -d)..." -ForegroundColor Cyan
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: docker compose up -d failed" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "`n[3/5] Waiting for all containers to become healthy (max 90s)..." -ForegroundColor Cyan
$timeout = 90
$interval = 5
$elapsed = 0
$allHealthy = $false

while ($elapsed -lt $timeout) {
    $allHealthy = $true
    foreach ($svc in $services) {
        $containerId = docker compose ps -q $svc 2>$null | Select-Object -First 1
        if (-not $containerId) {
            $allHealthy = $false
            Write-Host "  Waiting for service '$svc' container to appear..." -ForegroundColor Yellow
            break
        }
        $status = docker inspect --format '{{.State.Health.Status}}' $containerId 2>$null
        if ($status -ne "healthy") {
            $allHealthy = $false
            $display = if ($status) { $status } else { "unknown" }
            Write-Host "  Service '$svc' status: $display, waiting..." -ForegroundColor Yellow
            break
        }
    }
    if ($allHealthy) {
        Write-Host "  All services are healthy" -ForegroundColor Green
        break
    }
    Start-Sleep -Seconds $interval
    $elapsed += $interval
}

if (-not $allHealthy) {
    Write-Host "  ERROR: Timeout ($timeout s) - services not healthy" -ForegroundColor Red
    foreach ($svc in $services) {
        $cid = docker compose ps -q $svc 2>$null | Select-Object -First 1
        if ($cid) {
            $st = docker inspect --format '{{.State.Health.Status}}' $cid 2>$null
            Write-Host "     $svc : $(if($st){$st}else{'unavailable'})"
        } else {
            Write-Host "     $svc : not started"
        }
    }
    Write-Host "  Suggestion: check 'docker compose logs'" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n[4/5] Running data preparation and ingestion..." -ForegroundColor Cyan
$commands = @(
    @{ Name = "shopmind doctor"; Cmd = "uv run shopmind doctor" },
    @{ Name = "shopmind p1 run"; Cmd = "uv run shopmind p1 run" },
    @{ Name = "shopmind p2 ingest"; Cmd = "uv run shopmind p2 ingest" }
)

foreach ($step in $commands) {
    Write-Host "  Running $($step.Name) ..." -ForegroundColor Magenta
    Invoke-Expression $step.Cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: command '$($step.Cmd)' failed with exit code $LASTEXITCODE" -ForegroundColor Red
        Write-Host "  Suggestion: check logs and configuration" -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
    Write-Host "  $($step.Name) completed" -ForegroundColor Green
}

Write-Host "`n[5/5] Running P2 Demo (auto: in-domain QA, semantic cache, out-domain rejection)..." -ForegroundColor Cyan
Write-Host "  Executing: uv run shopmind p2 demo (non-interactive, exits after 3 acts)" -ForegroundColor Gray
uv run shopmind p2 demo
$demoExit = $LASTEXITCODE
if ($demoExit -ne 0) {
    Write-Host "  ERROR: p2 demo exited with code $demoExit" -ForegroundColor Red
    Write-Host "  Suggestion: check p2 code or run manually for details" -ForegroundColor Yellow
    exit $demoExit
}

Write-Host "`nAll steps completed successfully!" -ForegroundColor Green
exit 0