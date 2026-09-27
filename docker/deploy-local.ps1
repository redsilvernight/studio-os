<#
.SYNOPSIS
Deploy one verified origin/dev commit from a dedicated clone on Flo-laptop.

.DESCRIPTION
This command is intentionally local and one-shot. It does not poll GitHub and
does not install an inbound service or a self-hosted runner. Database migrations
are forward-only; an automatic code rollback never runs an Alembic downgrade.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$Revision,
    [string]$DeployDir = 'C:\Users\redsi\studio-os-deploy',
    [string]$Remote = 'origin',
    [string]$Branch = 'dev',
    [string]$ComposeProject = 'studio-os',
    [string]$ExpectedComputerName = 'FLO-LAPTOP',
    [string]$HealthUrl = 'https://flo-laptop.tailf61f85.ts.net/healthz',
    [string]$StorageHealthUrl = 'https://flo-laptop.tailf61f85.ts.net:8443/minio/health/live',
    [ValidateRange(30, 1800)]
    [int]$HealthTimeoutSeconds = 180,
    [ValidateRange(1, 100)]
    [int]$BackupRetention = 7,
    [switch]$SkipHostCheck,
    [switch]$Plan
)

$ErrorActionPreference = 'Stop'
$requiredRegistrationRoutes = @(
    '/api/v1/auth/register',
    '/api/v1/auth/resend-verification',
    '/api/v1/auth/verify-email'
)

function Get-DeploymentPlan {
    [ordered]@{
        revision = $Revision.ToLowerInvariant()
        source = "$Remote/$Branch"
        deploy_dir = $DeployDir
        compose_project = $ComposeProject
        steps = @(
            'acquire exclusive local lock',
            'verify dedicated clean clone and exact origin/dev commit',
            'validate docker compose configuration',
            'validate caddy configuration',
            'start postgres and minio',
            'backup postgres and minio',
            'build api, mcp and dashboard images',
            'run alembic upgrade head',
            'recreate application services and caddy',
            'verify health, A4 OpenAPI routes and storage health',
            'record deployed revision'
        )
        rollback = 'code only; database migrations are never downgraded automatically'
    }
}

if ($Plan) {
    Get-DeploymentPlan | ConvertTo-Json -Depth 4
    exit 0
}

function Write-DeployLog([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format s), $Message
    Add-Content -LiteralPath $script:LogFile -Value $line -Encoding utf8
    Write-Host $line
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments, [switch]$Capture) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "$FilePath $($Arguments -join ' ') failed ($exitCode): $($output -join [Environment]::NewLine)"
    }
    if ($Capture) { return $output }
    if ($output) { $output | Write-Host }
}

function Invoke-Git([string[]]$Arguments, [switch]$Capture) {
    Invoke-Native -FilePath 'git' -Arguments (@('-C', $DeployDir) + $Arguments) -Capture:$Capture
}

function Invoke-Compose([string[]]$Arguments, [switch]$Capture) {
    $base = @(
        'compose', '--project-name', $ComposeProject,
        '--env-file', $script:EnvFile,
        '-f', $script:BaseCompose
    )
    if (Test-Path -LiteralPath $script:HostCompose) { $base += @('-f', $script:HostCompose) }
    Invoke-Native -FilePath 'docker' -Arguments ($base + $Arguments) -Capture:$Capture
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $name, $value = $line -split '=', 2
        $values[$name.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $values
}

function New-DeploymentBackup([hashtable]$Environment) {
    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
    $destination = Join-Path $script:BackupRoot $timestamp
    $postgresDestination = Join-Path $destination 'postgres'
    $minioDestination = Join-Path $destination 'minio'
    New-Item -ItemType Directory -Force -Path $postgresDestination, $minioDestination | Out-Null

    $postgresContainer = ((Invoke-Compose @('ps', '-q', 'postgres') -Capture) | Select-Object -Last 1).Trim()
    if (-not $postgresContainer) { throw 'postgres container is not running' }
    Invoke-Compose @(
        'exec', '-T', 'postgres', 'pg_dump',
        '-U', $Environment.POSTGRES_USER,
        '-d', $Environment.POSTGRES_DB,
        '--format=custom', '--file=/tmp/studio-deploy.dump'
    )
    Invoke-Native 'docker' @('cp', "${postgresContainer}:/tmp/studio-deploy.dump", (Join-Path $postgresDestination 'studio.dump'))
    Invoke-Compose @('exec', '-T', 'postgres', 'rm', '-f', '/tmp/studio-deploy.dump')
    if ((Get-Item -LiteralPath (Join-Path $postgresDestination 'studio.dump')).Length -eq 0) {
        throw 'postgres backup is empty'
    }

    $mount = '{0}:/backup' -f $minioDestination
    $mirror = 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc mirror --overwrite "local/$MINIO_BUCKET" /backup'
    Invoke-Compose @('run', '--rm', '--no-deps', '-T', '-v', $mount, '-e', "MINIO_BUCKET=$($Environment.MINIO_BUCKET)", '--entrypoint', '/bin/sh', 'minio', '-c', $mirror)

    $backupRootFull = [IO.Path]::GetFullPath($script:BackupRoot)
    $oldBackups = Get-ChildItem -LiteralPath $backupRootFull -Directory | Sort-Object Name -Descending | Select-Object -Skip $BackupRetention
    foreach ($oldBackup in $oldBackups) {
        if (-not $oldBackup.FullName.StartsWith($backupRootFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to prune outside backup root: $($oldBackup.FullName)"
        }
        Remove-Item -LiteralPath $oldBackup.FullName -Recurse -Force
    }
    return $destination
}

function Wait-HttpOk([string]$Uri, [datetime]$Deadline) {
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri $Uri
            if ($response.StatusCode -eq 200) { return $response }
        }
        catch {
            Start-Sleep -Seconds 5
        }
    } while ((Get-Date) -lt $Deadline)
    throw "endpoint did not return HTTP 200 before timeout: $Uri"
}

if (-not $SkipHostCheck -and $env:COMPUTERNAME -ine $ExpectedComputerName) {
    throw "this deployment is restricted to $ExpectedComputerName (current host: $env:COMPUTERNAME); use -SkipHostCheck only for an intentional rehearsal"
}
foreach ($command in @('git', 'docker')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "required command not found: $command" }
}

$DeployDir = [IO.Path]::GetFullPath($DeployDir)
$marker = Join-Path $DeployDir '.studio-deploy-clone'
if (-not (Test-Path -LiteralPath (Join-Path $DeployDir '.git'))) { throw "deploy directory is not a git clone: $DeployDir" }
if (-not (Test-Path -LiteralPath $marker)) { throw "dedicated clone marker is missing: $marker" }

$script:DockerDir = Join-Path $DeployDir 'docker'
$script:EnvFile = Join-Path $script:DockerDir '.env'
$script:BaseCompose = Join-Path $script:DockerDir 'docker-compose.yml'
$script:HostCompose = Join-Path $script:DockerDir 'docker-compose.flo-laptop.yml'
$stateDir = Join-Path $env:LOCALAPPDATA 'studio-os-deploy'
$script:BackupRoot = Join-Path $script:DockerDir 'backups'
New-Item -ItemType Directory -Force -Path $stateDir, $script:BackupRoot | Out-Null
$script:LogFile = Join-Path $stateDir ('deploy-{0:yyyyMMdd}.log' -f (Get-Date))
$stateFile = Join-Path $stateDir 'state.json'
$lockPath = Join-Path $stateDir 'deploy.lock'
$lockStream = $null
$previousRevision = $null
$targetCheckedOut = $false

try {
    $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}
catch {
    throw 'another local deployment is already running'
}

try {
    $trackedChanges = ((Invoke-Git @('status', '--porcelain', '--untracked-files=no') -Capture) -join '').Trim()
    if ($trackedChanges) { throw 'the dedicated deployment clone has tracked changes' }
    if (-not (Test-Path -LiteralPath $script:EnvFile)) { throw "production environment file is missing: $script:EnvFile" }

    $environment = Read-DotEnv $script:EnvFile
    foreach ($required in @('POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'MINIO_ROOT_USER', 'MINIO_ROOT_PASSWORD', 'MINIO_BUCKET', 'STUDIO_JWT_SECRET', 'STUDIO_S3_PUBLIC_ENDPOINT_URL')) {
        if (-not $environment[$required]) { throw "missing required value in docker/.env: $required" }
        if ($environment[$required] -match 'change-me|example\.com') { throw "placeholder value remains in docker/.env: $required" }
    }
    if ($environment.STUDIO_S3_PUBLIC_ENDPOINT_URL -ne 'https://flo-laptop.tailf61f85.ts.net:8443') {
        throw 'STUDIO_S3_PUBLIC_ENDPOINT_URL must be https://flo-laptop.tailf61f85.ts.net:8443 on Flo-laptop'
    }

    Write-DeployLog "fetching $Remote/$Branch"
    Invoke-Git @('fetch', '--prune', $Remote, $Branch)
    Invoke-Git @('cat-file', '-e', "$Revision^{commit}")
    Invoke-Git @('merge-base', '--is-ancestor', $Revision, "$Remote/$Branch")
    $resolvedRevision = ((Invoke-Git @('rev-parse', $Revision) -Capture) | Select-Object -Last 1).Trim()
    if ($resolvedRevision -ine $Revision) { throw "revision did not resolve exactly: $Revision -> $resolvedRevision" }

    $previousRevision = ((Invoke-Git @('rev-parse', 'HEAD') -Capture) | Select-Object -Last 1).Trim()
    Write-DeployLog "deploying $Revision (previous code $previousRevision)"
    Invoke-Git @('switch', '--detach', $Revision)
    $targetCheckedOut = $true

    foreach ($requiredFile in @($script:BaseCompose, $script:HostCompose)) {
        if (-not (Test-Path -LiteralPath $requiredFile)) { throw "deployment file missing at target revision: $requiredFile" }
    }
    Invoke-Compose @('config', '--quiet')
    Invoke-Compose @('run', '--rm', '--no-deps', 'caddy', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile')
    Invoke-Compose @('up', '-d', 'postgres', 'minio', 'minio-init')
    $backup = New-DeploymentBackup $environment
    Write-DeployLog "backup complete: $backup"

    Write-DeployLog 'building api, mcp and dashboard images'
    Invoke-Compose @('build', 'api', 'mcp', 'dashboard')
    Write-DeployLog 'applying forward-only database migrations'
    Invoke-Compose @('run', '--rm', '--no-deps', 'api', 'alembic', 'upgrade', 'head')
    Write-DeployLog 'recreating application services and caddy'
    Invoke-Compose @('up', '-d', '--remove-orphans', 'postgres', 'minio', 'minio-init', 'api', 'mcp', 'dashboard', 'caddy')

    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    Wait-HttpOk $HealthUrl $deadline | Out-Null
    $openApiUrl = ([Uri]$HealthUrl).GetLeftPart([UriPartial]::Authority) + '/openapi.json'
    $openApi = (Wait-HttpOk $openApiUrl $deadline).Content | ConvertFrom-Json -AsHashtable
    foreach ($route in $requiredRegistrationRoutes) {
        if (-not $openApi.paths.ContainsKey($route)) { throw "deployed OpenAPI is missing required route: $route" }
    }
    Wait-HttpOk $StorageHealthUrl $deadline | Out-Null

    $state = [ordered]@{
        revision = $Revision.ToLowerInvariant()
        previous_revision = $previousRevision
        deployed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        backup = $backup
        health_url = $HealthUrl
        storage_health_url = $StorageHealthUrl
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
    Write-DeployLog "deployed OK: $Revision"
}
catch {
    if ($script:LogFile) { Write-DeployLog "FAILED: $($_.Exception.Message)" }
    if ($targetCheckedOut -and $previousRevision) {
        Write-DeployLog "rolling code back to $previousRevision; database migrations will not be downgraded"
        try {
            Invoke-Git @('switch', '--detach', $previousRevision)
            Invoke-Compose @('build', 'api', 'mcp', 'dashboard')
            Invoke-Compose @('up', '-d', '--remove-orphans', 'api', 'mcp', 'dashboard', 'caddy')
            Write-DeployLog "code rollback complete: $previousRevision"
        }
        catch {
            Write-DeployLog "code rollback failed: $($_.Exception.Message)"
        }
    }
    throw
}
finally {
    if ($lockStream) { $lockStream.Dispose() }
}
