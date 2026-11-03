# Claude Code PostToolUse (Edit|Write|MultiEdit): ruff format + safe fixes on
# the edited Python file, mirroring the CI `ruff format --check` / `ruff check`.
# Remaining lint errors are reported back to Claude (exit 2); never blocks
# anything else. Fail-open when ruff is unavailable.
$ErrorActionPreference = 'Stop'
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $path = [string]$payload.tool_input.file_path
} catch { exit 0 }
if (-not $path -or $path -notmatch '\.pyi?$' -or -not (Test-Path -LiteralPath $path)) { exit 0 }

$root = [string]($env:CLAUDE_PROJECT_DIR ?? $payload.cwd)
$ruff = Join-Path $root '.venv/Scripts/ruff.exe'
if (-not (Test-Path -LiteralPath $ruff)) { $ruff = Join-Path $root '.venv/bin/ruff' }
if (-not (Test-Path -LiteralPath $ruff)) { exit 0 }

Push-Location -LiteralPath $root
try {
    & $ruff format --quiet --force-exclude -- $path 2>$null | Out-Null
    $out = & $ruff check --fix --quiet --force-exclude --output-format concise -- $path 2>&1
    if ($LASTEXITCODE -ne 0 -and $out) {
        [Console]::Error.WriteLine("ruff check still reports issues:`n$($out -join "`n")")
        exit 2
    }
} finally { Pop-Location }
exit 0
