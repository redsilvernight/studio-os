[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $GraphifyArguments
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$localOutput = Join-Path $projectRoot 'graphify-out'
$centralOutput = 'E:\Graphify\Studio-OS\graphify-out'
$bundledExecutable = Join-Path $env:APPDATA 'uv\tools\graphifyy\Scripts\graphify.exe'

if (Test-Path -LiteralPath $localOutput) {
    throw "Refusing to run: an accidental local Graphify output already exists at '$localOutput'."
}

if (Test-Path -LiteralPath $bundledExecutable) {
    $graphifyExecutable = $bundledExecutable
}
else {
    $resolvedCommand = Get-Command 'graphify.exe' -ErrorAction Stop
    $graphifyExecutable = $resolvedCommand.Source
}

$previousOutput = $env:GRAPHIFY_OUT
$env:GRAPHIFY_OUT = $centralOutput

try {
    & $graphifyExecutable @GraphifyArguments
    $graphifyExitCode = $LASTEXITCODE
}
finally {
    if ($null -eq $previousOutput) {
        Remove-Item Env:GRAPHIFY_OUT -ErrorAction SilentlyContinue
    }
    else {
        $env:GRAPHIFY_OUT = $previousOutput
    }
}

if (Test-Path -LiteralPath $localOutput) {
    throw "Graphify created an unexpected local output at '$localOutput'. The central output is '$centralOutput'."
}

exit $graphifyExitCode
