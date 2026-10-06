#Requires -Version 7
<#
.SYNOPSIS
  Starts what the test suite needs: Docker Desktop, PostgreSQL (migrated to head) and MinIO.
  Idempotent; prints the STUDIO_TEST_DATABASE_URL to use.
#>
[CmdletBinding()]
param(
    [string]$Postgres = "studio-os-test-pg",
    [string]$Minio = "studio-os-test-minio",
    [string]$Database = "studio_os_test",
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$url = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/$Database"

function Wait-Until([scriptblock]$Ready, [string]$What) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (& $Ready)) {
        if ((Get-Date) -gt $deadline) { throw "Timed out waiting for $What" }
        Start-Sleep -Seconds 2
    }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Wait-Until { docker info *> $null; $LASTEXITCODE -eq 0 } "Docker"
}

foreach ($name in $Postgres, $Minio) {
    if ((docker inspect -f "{{.State.Running}}" $name 2>$null) -ne "true") {
        docker start $name | Out-Null
    }
}
Wait-Until { docker exec $Postgres pg_isready -U studio *> $null; $LASTEXITCODE -eq 0 } "PostgreSQL"
Wait-Until {
    try { (Invoke-WebRequest "http://127.0.0.1:9000/minio/health/live" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 }
    catch { $false }
} "MinIO"

Push-Location (Join-Path $root "services/api")
try {
    $env:STUDIO_DATABASE_URL = $url
    uv run alembic upgrade head 2>&1 | Select-Object -Last 1
}
finally { Pop-Location }

Write-Output "ready: `$env:STUDIO_TEST_DATABASE_URL = '$url'"
