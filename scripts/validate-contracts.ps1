#Requires -Version 7
<#
.SYNOPSIS
  Validates the contracts perimeter: pytest tests/contracts + ruff + mypy.
  Needs no PostgreSQL/MinIO/Docker (tests/contracts is infra-free).

.NOTES
  Exit codes: 0 = everything passed; 1 = tests failed; 2 = ruff failed;
  3 = mypy failed; 4 = tool/launch error (uv missing, pytest no tests, ...).
  All three steps always run so one report shows every failure; the exit code is
  that of the first failing step in the order tests, ruff, mypy.
#>
[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$contracts = "packages/studio-contracts"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "uv not found on PATH"
    exit 4
}

function Invoke-Step([string]$Name, [int]$FailCode, [string[]]$UvArgs) {
    Write-Host "== $Name"
    $proc = Start-Process -FilePath "uv" -ArgumentList $UvArgs -WorkingDirectory $root `
        -NoNewWindow -PassThru
    if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
        $proc.Kill($true)
        Write-Host "$Name : TIMEOUT after ${TimeoutSeconds}s"
        return 4
    }
    if ($proc.ExitCode -eq 0) { Write-Host "$Name : OK"; return 0 }
    # pytest: 5 = no tests collected is a launch/selection error, not a test failure.
    if ($Name -eq "pytest" -and $proc.ExitCode -eq 5) { Write-Host "$Name : no tests collected"; return 4 }
    Write-Host "$Name : FAILED (exit $($proc.ExitCode))"
    return $FailCode
}

$results = @(
    Invoke-Step "pytest" 1 @("run", "pytest", "tests/contracts", "-q", "-p", "no:cacheprovider", "-m", "not infra")
    Invoke-Step "ruff" 2 @("run", "ruff", "check", $contracts, "tests/contracts")
    Invoke-Step "mypy" 3 @("run", "mypy", "$contracts/src")
)

$failed = $results | Where-Object { $_ -ne 0 } | Select-Object -First 1
if ($null -eq $failed) {
    Write-Host "validate-contracts: OK"
    exit 0
}
Write-Host "validate-contracts: FAILED (exit $failed)"
exit $failed
