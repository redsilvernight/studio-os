#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Register this machine as a self-hosted GitHub Actions runner for the
    Studio OS production deployment (see .github/workflows/deploy.yml).

.DESCRIPTION
    Downloads the latest actions/runner (win-x64), registers it against the
    repository with the `studio-deploy` label, installs it as a Windows
    service and starts it.

    Docker Desktop on Windows exposes its engine through a per-user named
    pipe (\\.\pipe\dockerDesktopLinuxEngine). A service running as LocalSystem
    usually CANNOT reach it, so the deploy workflow's `docker compose` calls
    would fail. If you omit -ServiceUser, the script installs the service as
    LocalSystem and prints a warning; pass -ServiceUser/-ServicePassword with
    the account that owns the Docker Desktop session (and is in the
    `docker-users` group) to run the service under it instead.

.PARAMETER Token
    Runner registration token. GitHub repo -> Settings -> Actions -> Runners
    -> New self-hosted runner (the token in the shown command, valid ~1h).
    Also obtainable via the API:
      POST /repos/{owner}/{repo}/actions/runners/registration-token

.PARAMETER ServiceUser
    Optional. Account to run the service as, e.g. "HOSTNAME\redsi" or ".\redsi".
    Required in practice for Docker Desktop access.

.EXAMPLE
    .\install-runner.ps1 -Token <TOKEN> -ServiceUser ".\redsi" -ServicePassword (Read-Host -AsSecureString)
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [string]$RepoUrl   = 'https://github.com/redsilvernight/studio-os',
    [string]$RunnerDir = 'C:\actions-runner',
    [string]$RunnerName = $env:COMPUTERNAME,
    [string]$Labels    = 'studio-deploy',
    [string]$Version,

    [string]$ServiceUser,
    [System.Security.SecureString]$ServicePassword
)

$ErrorActionPreference = 'Stop'

if (-not $Version) {
    Write-Host 'Resolving latest actions/runner version...'
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/runner/releases/latest' `
        -Headers @{ 'User-Agent' = 'studio-os-installer' }
    $Version = $release.tag_name.TrimStart('v')
}
Write-Host "Runner version: $Version"

New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null

if (-not (Test-Path (Join-Path $RunnerDir 'config.cmd'))) {
    $zipName = "actions-runner-win-x64-$Version.zip"
    $zipPath = Join-Path $env:TEMP $zipName
    $url = "https://github.com/actions/runner/releases/download/v$Version/$zipName"
    Write-Host "Downloading $url ..."
    Invoke-WebRequest -Uri $url -OutFile $zipPath
    Write-Host "Extracting to $RunnerDir ..."
    Expand-Archive -Path $zipPath -DestinationPath $RunnerDir -Force
}

Push-Location $RunnerDir
try {
    Write-Host 'Registering runner...'
    & .\config.cmd --url $RepoUrl --token $Token --name $RunnerName `
        --labels $Labels --unattended --replace
    if ($LASTEXITCODE -ne 0) { throw "config.cmd failed (exit $LASTEXITCODE)" }

    Write-Host 'Installing runner Windows service...'
    & .\svc.cmd install
    if ($LASTEXITCODE -ne 0) { throw "svc.cmd install failed (exit $LASTEXITCODE)" }

    $service = (Get-Service | Where-Object { $_.Name -like 'actions.runner.*' }).Name
    if (-not $service) { throw 'runner service not found after install' }
    Write-Host "Runner service: $service"

    if ($ServiceUser) {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ServicePassword))
        Write-Host "Configuring service to run as $ServiceUser ..."
        & sc.exe config $service "obj= $ServiceUser" "password= $plain" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "sc.exe config failed (exit $LASTEXITCODE)" }
    }
    else {
        Write-Warning ('Service installed as LocalSystem. Docker Desktop''s engine pipe is ' +
            'per-user and likely unreachable from LocalSystem — if the deploy workflow cannot ' +
            'run docker, reconfigure with: sc.exe config "{0}" obj= ".\<user>" password= "<pw>"' -f $service)
    }

    Write-Host 'Starting runner service...'
    & .\svc.cmd start
    if ($LASTEXITCODE -ne 0) { throw "svc.cmd start failed (exit $LASTEXITCODE)" }

    & .\svc.cmd status
    Write-Host ''
    Write-Host "Runner '$RunnerName' registered with labels '$Labels'."
    Write-Host "Verify it shows as Idle at: $RepoUrl/settings/actions/runners"
}
finally {
    Pop-Location
}
