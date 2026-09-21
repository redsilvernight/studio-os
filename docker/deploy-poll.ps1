<#
.SYNOPSIS
    Poll-based continuous deployment for Studio OS production.

.DESCRIPTION
    A self-hosted GitHub Actions runner cannot run on this host (Device Guard /
    WDAC blocks Runner.Listener.exe) and WSL exposes no general-purpose distro,
    so CD is driven by a Windows Scheduled Task instead. This script is the
    polling half: it checks the deployment branch on GitHub and, when the tip
    differs from the last successfully deployed revision, rebuilds the
    application images, applies migrations, recreates the services and waits
    for the API health check. On failure it rolls the code back.

    It deploys the canonical working copy ($DeployDir), so gitignored
    production state (docker/.env, docker/.data, docker/backups) is preserved.
    Database migrations are forward-only: a code rollback does NOT revert them.

.PARAMETER Force
    Deploy even if the tip already matches the last deployed revision, and
    retry a revision previously marked as failed.

.NOTES
    Register the schedule with docker/install-deploy-task.ps1.
#>
[CmdletBinding()]
param(
    [string]$DeployDir = 'C:\Users\redsi\studio-os-deploy',
    [string]$Branch = 'deploy/flo-laptop',
    [string]$Remote = 'origin',
    [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'studio-os-deploy'),
    [int]$HealthTimeoutSeconds = 180,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$logFile = Join-Path $StateDir ('deploy-{0:yyyyMMdd}.log' -f (Get-Date))
$lockFile = Join-Path $StateDir 'deploy.lock'
$stateFile = Join-Path $StateDir 'deployed.rev'
$failFile = Join-Path $StateDir 'failed.rev'

function Write-Log([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format s), $Message
    Add-Content -Path $logFile -Value $line -Encoding utf8
    Write-Host $line
}

function Invoke-Git([string[]]$GitArgs) {
    $out = & git -C $DeployDir @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed ($LASTEXITCODE): $out"
    }
    return $out
}

if (-not (Test-Path -LiteralPath (Join-Path $DeployDir '.git'))) {
    Write-Log "deploy directory is not a git clone: $DeployDir"
    exit 2
}

# Single instance: a left-over lock older than 2h is considered stale.
if (Test-Path -LiteralPath $lockFile) {
    $age = (Get-Date) - (Get-Item -LiteralPath $lockFile).LastWriteTime
    if ($age.TotalHours -lt 2) {
        Write-Host 'another deployment is already running; skipping'
        exit 0
    }
}
New-Item -ItemType File -Path $lockFile -Force | Out-Null

$prev = $null
$target = $null
try {
    Invoke-Git @('fetch', '--prune', $Remote, $Branch) | Out-Null
    $target = (Invoke-Git @('rev-parse', "$Remote/$Branch") | Select-Object -Last 1).Trim()
    $deployed = if (Test-Path -LiteralPath $stateFile) { (Get-Content -LiteralPath $stateFile -Raw).Trim() } else { '' }
    $failed = if (Test-Path -LiteralPath $failFile) { (Get-Content -LiteralPath $failFile -Raw).Trim() } else { '' }

    if (-not $Force) {
        if ($target -eq $deployed) { Write-Host "up to date at $target"; exit 0 }
        if ($target -eq $failed) { Write-Host "revision $target previously failed; waiting for a new commit"; exit 0 }
    }

    $prev = (Invoke-Git @('rev-parse', 'HEAD') | Select-Object -Last 1).Trim()
    Write-Log "deploying $target (previous code $prev)"

    Invoke-Git @('reset', '--hard', $target) | Out-Null

    Set-Location -LiteralPath (Join-Path $DeployDir 'docker')

    Write-Log 'building images (api, mcp, dashboard)'
    & docker compose build api mcp dashboard
    if ($LASTEXITCODE -ne 0) { throw "docker compose build failed ($LASTEXITCODE)" }

    Write-Log 'applying database migrations'
    & docker compose run --rm api alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed ($LASTEXITCODE)" }

    Write-Log 'recreating application services'
    & docker compose up -d --no-deps api mcp dashboard
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed ($LASTEXITCODE)" }

    Write-Log "waiting for API health (max ${HealthTimeoutSeconds}s)"
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        try {
            if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri 'http://localhost/healthz').StatusCode -eq 200) {
                $healthy = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 5
    }
    if (-not $healthy) { throw 'API did not become healthy in time' }

    Set-Content -LiteralPath $stateFile -Value $target -Encoding ascii
    Remove-Item -LiteralPath $failFile -ErrorAction SilentlyContinue
    Write-Log "deployed OK: $target"
    exit 0
}
catch {
    Write-Log "FAILED: $($_.Exception.Message)"
    if ($target) { Set-Content -LiteralPath $failFile -Value $target -Encoding ascii }
    if ($prev) {
        Write-Log "rolling code back to $prev"
        try {
            Invoke-Git @('reset', '--hard', $prev) | Out-Null
            Set-Location -LiteralPath (Join-Path $DeployDir 'docker')
            & docker compose build api mcp dashboard
            & docker compose up -d --no-deps api mcp dashboard
            Write-Log "code rolled back to $prev (migrations were NOT reverted)"
        }
        catch {
            Write-Log "rollback failed: $($_.Exception.Message)"
        }
    }
    exit 1
}
finally {
    Remove-Item -LiteralPath $lockFile -ErrorAction SilentlyContinue
}
