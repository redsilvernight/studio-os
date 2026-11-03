#Requires -Version 7
[CmdletBinding()]
param(
    [string]$Postgres = "studio-os-test-pg",
    [string]$Minio = "studio-os-test-minio",
    [string]$Database = "studio_os_test",
    [string]$DatabaseUrl = $env:STUDIO_TEST_DATABASE_URL,
    [string]$StorageEndpoint = $env:STUDIO_S3_ENDPOINT_URL,
    [switch]$StartServices,
    [switch]$Migrate,
    [ValidateRange(1, 300)][int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    $DatabaseUrl = "postgresql+asyncpg://studio:studio@127.0.0.1:5432/$Database"
}
if ([string]::IsNullOrWhiteSpace($StorageEndpoint)) {
    $StorageEndpoint = "http://127.0.0.1:9000"
}
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "environment_unavailable: project Python is missing; run uv sync --all-packages." -ErrorAction Continue
    exit 2
}

function Wait-Until([scriptblock]$Ready, [string]$What) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (-not (& $Ready)) {
        if ((Get-Date) -gt $deadline) { throw "Timed out waiting for $What" }
        Start-Sleep -Seconds 2
    }
}

function Invoke-Alembic([string[]]$Arguments) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $python
    $startInfo.WorkingDirectory = Join-Path $root 'services/api'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in @('-m', 'alembic') + $Arguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        $null = $process.Start()
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $process.Kill($true)
            $process.WaitForExit()
            throw "Database check timed out after $TimeoutSeconds seconds."
        }
        $null = $output.GetAwaiter().GetResult()
        $null = $errors.GetAwaiter().GetResult()
        return $process.ExitCode
    }
    finally { $process.Dispose() }
}

try {
    if ($StartServices -or $Migrate) {
        $databaseUri = [Uri]($DatabaseUrl -replace '^postgresql\+asyncpg:', 'postgresql:')
        $databaseName = $databaseUri.AbsolutePath.Trim('/')
        if ($databaseUri.Host -notin @('127.0.0.1', 'localhost', '[::1]') -or
            $databaseName -notmatch '(^test_|_test$)') {
            throw "Service startup and migrations require a local test database."
        }
    }
    if ($StartServices) {
        if ($databaseUri.Port -ne 5432 -or $StorageEndpoint.TrimEnd('/') -ne 'http://127.0.0.1:9000') {
            throw "StartServices only manages the standard test containers; custom endpoints are check-only."
        }
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw "Docker is missing; use existing native test endpoints instead."
        }
        docker info *> $null
        if ($LASTEXITCODE -ne 0) {
            $memory = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
            $commitFree = [double]$memory.CommitLimit - [double]$memory.CommittedBytes
            if ($commitFree -lt 16GB -or [double]$memory.AvailableMBytes -lt 4096) {
                throw "Insufficient memory headroom to start Docker (16 GiB commit and 4 GiB RAM required)."
            }
            Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
            Wait-Until { docker info *> $null; $LASTEXITCODE -eq 0 } "Docker"
        }
        foreach ($name in $Postgres, $Minio) {
            if ((docker inspect -f "{{.State.Running}}" $name 2>$null) -ne "true") {
                docker start $name | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Could not start test container $name." }
            }
        }
        Wait-Until { docker exec $Postgres pg_isready -U studio *> $null; $LASTEXITCODE -eq 0 } "PostgreSQL"
    }
    $health = $StorageEndpoint.TrimEnd('/') + '/minio/health/live'
    $response = Invoke-WebRequest $health -UseBasicParsing -TimeoutSec 3
    if ($response.StatusCode -ne 200) { throw "MinIO is unavailable." }
    $previousDatabaseUrl = $env:STUDIO_DATABASE_URL
    $previousConnectTimeout = $env:PGCONNECT_TIMEOUT
    Push-Location (Join-Path $root "services/api")
    try {
        $env:STUDIO_DATABASE_URL = $DatabaseUrl
        $env:PGCONNECT_TIMEOUT = '3'
        if ($Migrate) {
            $migrationExit = Invoke-Alembic -Arguments @('upgrade', 'head')
            if ($migrationExit -ne 0) { throw "Migration failed (exit $migrationExit)." }
        }
        $probeExit = Invoke-Alembic -Arguments @('current', '--check-heads')
        if ($probeExit -ne 0) {
            throw "Database unavailable or schema not at head (exit $probeExit). Use -Migrate explicitly for a local test database."
        }
    }
    finally {
        $env:STUDIO_DATABASE_URL = $previousDatabaseUrl
        $env:PGCONNECT_TIMEOUT = $previousConnectTimeout
        Pop-Location
    }
    Write-Output "ready: PostgreSQL schema at head; MinIO reachable. No service started unless -StartServices; no migration unless -Migrate."
    exit 0
}
catch {
    Write-Error "environment_unavailable: $($_.Exception.Message)" -ErrorAction Continue
    exit 2
}
