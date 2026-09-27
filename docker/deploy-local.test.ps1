$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'deploy-local.ps1'
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw "PowerShell parse errors: $($errors -join '; ')" }

$revision = '0123456789abcdef0123456789abcdef01234567'
$plan = (& $scriptPath -Revision $revision -Plan | ConvertFrom-Json)
if ($plan.revision -ne $revision) { throw 'plan does not retain the exact revision' }
if ($plan.source -ne 'origin/dev') { throw 'plan source must be origin/dev' }
if ($plan.steps.Count -lt 8) { throw 'deployment plan is unexpectedly incomplete' }
if ($plan.rollback -notmatch 'never downgraded') { throw 'migration rollback guard is missing' }

$source = Get-Content -LiteralPath $scriptPath -Raw
foreach ($required in @(
    'merge-base',
    '--is-ancestor',
    'docker-compose.flo-laptop.yml',
    "'caddy', 'validate'",
    "'caddy', 'reload'",
    "'/mcp'",
    'backup postgres and minio',
    '/openapi.json',
    '/api/v1/auth/register',
    '/api/v1/auth/resend-verification',
    '/api/v1/auth/verify-email',
    'database migrations will not be downgraded'
)) {
    if (-not $source.Contains($required)) { throw "required deployment guard is missing: $required" }
}
foreach ($forbidden in @('deploy/flo-laptop', 'reset --hard', 'alembic downgrade')) {
    if ($source.Contains($forbidden)) { throw "forbidden deployment behavior found: $forbidden" }
}

$invalidRejected = $false
try { & $scriptPath -Revision 'dev' -Plan | Out-Null }
catch { $invalidRejected = $true }
if (-not $invalidRejected) { throw 'a symbolic or abbreviated revision was accepted' }

Write-Host 'deploy-local tests passed'
