[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true, Position = 0)]
    [string[]] $GraphifyArguments,
    [string[]] $ChangedPaths
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
    if ($ChangedPaths.Count -gt 0) {
        if ($GraphifyArguments.Count -gt 0) {
            throw 'ChangedPaths cannot be combined with GraphifyArguments.'
        }
        $projectPrefix = $projectRoot + [IO.Path]::DirectorySeparatorChar
        $resolvedPaths = foreach ($changedPath in $ChangedPaths) {
            $targetPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $changedPath))
            if (-not $targetPath.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Changed path is outside the project: '$changedPath'."
            }
            if (Test-Path -LiteralPath $targetPath -PathType Container) {
                throw "Changed path must be a file: '$changedPath'."
            }
            $targetPath
        }
        $graphifyPython = Join-Path (Split-Path -Parent $graphifyExecutable) 'python.exe'
        $updateCode = 'import json,sys; from pathlib import Path; from graphify.watch import _rebuild_code; sys.exit(0 if _rebuild_code(Path(sys.argv[1]), changed_paths=[Path(p) for p in json.loads(sys.argv[2])], block_on_lock=True) else 1)'
        & $graphifyPython -c $updateCode $projectRoot (ConvertTo-Json -InputObject @($resolvedPaths) -Compress)
    }
    else {
        & $graphifyExecutable @GraphifyArguments
    }
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
