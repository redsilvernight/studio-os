<#
.SYNOPSIS
    Register the Studio OS poll-based CD task (see docker/deploy-poll.ps1).

.DESCRIPTION
    Creates (or replaces) a Scheduled Task that runs deploy-poll.ps1 every
    $IntervalMinutes minutes while the current user is logged on. Runs as the
    current user at limited privilege, so it can reach the per-user Docker
    Desktop engine pipe (dockerDesktopLinuxEngine) — a SYSTEM service could
    not.

.PARAMETER RunNow
    Start the task immediately after registering it.
#>
[CmdletBinding()]
param(
    [string]$DeployDir = 'C:\Users\redsi\studio-os-deploy',
    [string]$Branch = 'deploy/flo-laptop',
    [string]$ComposeProject = 'studio-os',
    [int]$IntervalMinutes = 5,
    [string]$TaskName = 'StudioOS-DeployPoll',
    [switch]$RunNow
)

$ErrorActionPreference = 'Stop'

$script = Join-Path $DeployDir 'docker\deploy-poll.ps1'
if (-not (Test-Path -LiteralPath $script)) { throw "deploy-poll.ps1 not found at $script" }

$argument = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass ' +
    "-File `"$script`" -DeployDir `"$DeployDir`" -Branch `"$Branch`" -ComposeProject `"$ComposeProject`""

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument `
    -WorkingDirectory (Join-Path $DeployDir 'docker')

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -User $env:USERNAME -RunLevel Limited -Force | Out-Null

Write-Host "scheduled task '$TaskName' registered (every $IntervalMinutes min, user $env:USERNAME)"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "task '$TaskName' started"
}
