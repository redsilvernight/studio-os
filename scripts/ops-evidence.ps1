#Requires -Version 7
[CmdletBinding()]
param(
    [string]$TemplateContainer = 'studio-os-test-pg',
    [ValidatePattern('^studio_os_ops_[a-z0-9_]+$')]
    [string]$TemplateDatabase = 'studio_os_ops_bb335466',
    [string]$OutputRoot = 'output/ops-evidence',
    [string]$Bash = 'C:/Program Files/Git/bin/bash.exe'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runId = 'ops-bb335466-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$runRoot = [IO.Path]::GetFullPath((Join-Path $root (Join-Path $OutputRoot $runId)))
if (-not $runRoot.StartsWith($root + [IO.Path]::DirectorySeparatorChar, 'OrdinalIgnoreCase')) {
    throw 'OutputRoot must stay inside this checkout.'
}
if (-not (Test-Path -LiteralPath $Bash -PathType Leaf)) { throw "Bash not found: $Bash" }
New-Item -ItemType Directory -Path $runRoot | Out-Null
$log = Join-Path $runRoot 'recovery.log'
$started = [DateTime]::UtcNow.ToString('o')
$receipt = [ordered]@{
    schema_version = 1
    task_id = 'bb335466-469f-4e92-a044-dcd077f54971'
    run_id = $runId
    started_at = $started
    checkout_commit = (& git -C $root rev-parse HEAD).Trim()
    status = 'running'
    template_database = $TemplateDatabase
    projects = @("$runId-source", "$runId-restore")
    scripts_sha256 = @{}
    runner_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
}
$previousProject = $env:COMPOSE_PROJECT_NAME
$previousComposeFile = $env:COMPOSE_FILE
$previousEnvFiles = $env:COMPOSE_ENV_FILES
$previousPathConversion = $env:MSYS_NO_PATHCONV
$previousProcedure = $env:STUDIO_OPS_PROCEDURE
$previousBackup = $env:STUDIO_OPS_BACKUP
Remove-Item Env:COMPOSE_FILE, Env:COMPOSE_ENV_FILES -ErrorAction SilentlyContinue
$env:MSYS_NO_PATHCONV = '1'

function Invoke-Docker([string[]]$Arguments) {
    Add-Content -LiteralPath $log -Value ('docker ' + ($Arguments -join ' '))
    $result = & docker @Arguments 2>&1
    $code = $LASTEXITCODE
    $result | ForEach-Object { Add-Content -LiteralPath $log -Value "$_" }
    if ($code -ne 0) { throw "Docker failed ($code): $($Arguments -join ' ')" }
    return ($result | ForEach-Object { "$_" })
}

function Invoke-Compose([string]$Side, [string[]]$Arguments) {
    $env:COMPOSE_PROJECT_NAME = "$runId-$Side"
    $compose = Join-Path $runRoot "$Side/docker-compose.yml"
    Invoke-Docker (@('compose', '-f', $compose) + $Arguments)
}

function Read-Database([string]$Side, [string]$Sql) {
    return ((Invoke-Compose $Side @('exec', '-T', 'postgres', 'psql', '-U', 'studio', '-d', 'evidence', '-qAt', '-v', 'ON_ERROR_STOP=1', '-c', $Sql)) -join "`n").Trim()
}

function Invoke-Procedure([string]$Side, [string]$Name, [string]$Backup) {
    $env:COMPOSE_PROJECT_NAME = "$runId-$Side"
    Add-Content -LiteralPath $log -Value "$Side/$Name $Backup"
    $env:STUDIO_OPS_PROCEDURE = (Join-Path $runRoot "$Side/$Name").Replace('\', '/')
    $env:STUDIO_OPS_BACKUP = $Backup
    $result = & $Bash -c 'exec bash "$STUDIO_OPS_PROCEDURE" "$STUDIO_OPS_BACKUP"' 2>&1
    $code = $LASTEXITCODE
    $result | ForEach-Object { Add-Content -LiteralPath $log -Value "$_" }
    if ($code -ne 0) { throw "$Name failed ($code). See $log" }
}

$composeText = @'
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: studio
      POSTGRES_PASSWORD: evidence-only-password
      POSTGRES_DB: evidence
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "studio", "-d", "evidence"]
      interval: 2s
      timeout: 3s
      retries: 30
  minio:
    image: pgsty/minio:latest@sha256:b6bfe7239bfc83fb90d31612d9704d86039dd714f7904b3f1ad68f211e602372
    command: server /data
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 2s
      timeout: 3s
      retries: 30
volumes:
  postgres_data:
  minio_data:
'@
$dotenv = "POSTGRES_USER=studio`nPOSTGRES_DB=evidence`nMINIO_ROOT_USER=minioadmin`nMINIO_ROOT_PASSWORD=minioadmin`nMINIO_BUCKET=ops-evidence`n"
$countsSql = @'
CREATE TEMP TABLE evidence_counts (name text, n bigint);
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('INSERT INTO evidence_counts SELECT %L, count(*) FROM public.%I', r.tablename, r.tablename);
  END LOOP;
END $$;
SELECT jsonb_object_agg(name,n) FROM evidence_counts;
'@

try {
    foreach ($side in 'source', 'restore') {
        $dir = Join-Path $runRoot $side
        New-Item -ItemType Directory -Path $dir | Out-Null
        [IO.File]::WriteAllText((Join-Path $dir 'docker-compose.yml'), $composeText)
        [IO.File]::WriteAllText((Join-Path $dir '.env'), $dotenv)
        foreach ($name in 'backup.sh', 'restore.sh', 'dotenv.sh') {
            $original = Join-Path $root "docker/$name"
            $receipt.scripts_sha256[$name] = (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash
            $content = [IO.File]::ReadAllText($original).Replace("`r`n", "`n")
            [IO.File]::WriteAllText((Join-Path $dir $name), $content)
        }
    }
    $schemaPath = "/tmp/$runId.dump"
    Invoke-Docker @('exec', $TemplateContainer, 'pg_dump', '-U', 'studio', '-d', $TemplateDatabase, '--schema-only', '--format=custom', '-f', $schemaPath) | Out-Null
    $schemaFile = Join-Path $runRoot 'schema.dump'
    Invoke-Docker @('cp', "${TemplateContainer}:$schemaPath", $schemaFile) | Out-Null
    $version = ((Invoke-Docker @('exec', $TemplateContainer, 'psql', '-U', 'studio', '-d', $TemplateDatabase, '-At', '-c', 'SELECT version_num FROM alembic_version')) -join '').Trim()
    if ($version -notmatch '^[a-zA-Z0-9_]+$') { throw 'Expected one Alembic revision.' }
    Invoke-Compose 'source' @('up', '-d', '--wait', '--wait-timeout', '90') | Out-Null
    $sourcePg = ((Invoke-Compose 'source' @('ps', '-q', 'postgres')) -join '').Trim()
    Invoke-Docker @('cp', $schemaFile, "${sourcePg}:/tmp/schema.dump") | Out-Null
    Invoke-Compose 'source' @('exec', '-T', 'postgres', 'pg_restore', '-U', 'studio', '-d', 'evidence', '--no-owner', '/tmp/schema.dump') | Out-Null
    Read-Database 'source' "INSERT INTO alembic_version VALUES ('$version'); CREATE TABLE ops_evidence_marker (id integer PRIMARY KEY, payload text NOT NULL); INSERT INTO ops_evidence_marker VALUES (1, '$runId');" | Out-Null
    $object = "restorable-object-$runId"
    $mc = 'mc alias set proof http://127.0.0.1:9000 minioadmin minioadmin >/dev/null && '
    Invoke-Compose 'source' @('exec', '-T', 'minio', '/bin/sh', '-c', ($mc + "mc mb proof/ops-evidence && printf '%s' '$object' | mc pipe proof/ops-evidence/roundtrip.txt")) | Out-Null
    $before = Read-Database 'source' $countsSql
    $backupRoot = (Join-Path $runRoot 'backups').Replace('\', '/')
    Invoke-Procedure 'source' 'backup.sh' $backupRoot
    $backup = @(Get-ChildItem -LiteralPath $backupRoot -Directory)
    if ($backup.Count -ne 1) { throw 'Expected exactly one fresh backup.' }
    Invoke-Compose 'source' @('stop') | Out-Null
    Invoke-Compose 'restore' @('up', '-d', '--wait', '--wait-timeout', '90') | Out-Null
    $empty = Read-Database 'restore' "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
    if ($empty -ne '0') { throw 'Restore database was not empty.' }
    $objectsBefore = ((Invoke-Compose 'restore' @('exec', '-T', 'minio', '/bin/sh', '-c', ($mc + 'mc ls proof'))) -join '').Trim()
    if ($objectsBefore) { throw 'Restore object storage was not empty.' }
    Invoke-Procedure 'restore' 'restore.sh' $backup[0].FullName.Replace('\', '/')
    $after = Read-Database 'restore' $countsSql
    $restoredVersion = Read-Database 'restore' 'SELECT version_num FROM alembic_version'
    $marker = Read-Database 'restore' 'SELECT payload FROM ops_evidence_marker WHERE id=1'
    $restoredObject = ((Invoke-Compose 'restore' @('exec', '-T', 'minio', '/bin/sh', '-c', ($mc + 'mc cat proof/ops-evidence/roundtrip.txt'))) -join '').Trim()
    if ($before -ne $after -or $version -ne $restoredVersion -or $marker -ne $runId -or $restoredObject -ne $object) {
        throw 'Restored database or object differs from source.'
    }
    $receipt.status = 'passed'
    $receipt.alembic_revision = $restoredVersion
    $receipt.source_row_counts = $before | ConvertFrom-Json -AsHashtable
    $receipt.row_counts = $after | ConvertFrom-Json -AsHashtable
    $receipt.restore_initial_public_tables = [int]$empty
    $receipt.restore_initial_buckets = 0
    $receipt.source_stopped_before_restore = $true
    $receipt.object_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($restoredObject))).ToLowerInvariant()
    $receipt.backup_sha256 = (Get-FileHash -LiteralPath (Join-Path $backup[0].FullName 'postgres/studio.dump') -Algorithm SHA256).Hash
}
catch {
    $receipt.status = 'failed'
    $receipt.error = $_.Exception.Message
    throw
}
finally {
    $stopFailures = @()
    foreach ($side in 'source', 'restore') {
        try { Invoke-Compose $side @('stop') | Out-Null }
        catch { $stopFailures += $_.Exception.Message }
    }
    $receipt.stop_failures = $stopFailures
    if ($stopFailures.Count) { $receipt.status = 'failed' }
    $receipt.finished_at = [DateTime]::UtcNow.ToString('o')
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runRoot 'recovery.json')
    $env:COMPOSE_PROJECT_NAME = $previousProject
    $env:COMPOSE_FILE = $previousComposeFile
    $env:COMPOSE_ENV_FILES = $previousEnvFiles
    $env:MSYS_NO_PATHCONV = $previousPathConversion
    $env:STUDIO_OPS_PROCEDURE = $previousProcedure
    $env:STUDIO_OPS_BACKUP = $previousBackup
    Write-Output "Recovery $($receipt.status): $runRoot"
    if ($stopFailures.Count) { throw ($stopFailures -join '; ') }
}
