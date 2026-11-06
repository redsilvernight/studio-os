# Studio OS hook session-start (session_start, advisory). Prints context; never blocks.
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try { $evt = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { $evt = $null }
$cwd = if ($evt.cwd) { [string]$evt.cwd } elseif ($evt.input.cwd) { [string]$evt.input.cwd } else { (Get-Location).Path }
if (-not (git -C $cwd rev-parse --is-inside-work-tree 2>$null)) { exit 0 }

$norm = { param($x) [IO.Path]::GetFullPath([string]$x).TrimEnd('\', '/') }
$here = & $norm $cwd
$sep = [IO.Path]::DirectorySeparatorChar
# cwd is the root, below it, or in a sibling task worktree "<root>-wt-<8hex>"
$under = {
    param($root)
    $r = & $norm $root
    if ($here -ieq $r -or $here.StartsWith($r + $sep, 'OrdinalIgnoreCase')) { return $true }
    return [bool]($here -imatch ('^' + [regex]::Escape($r) + '-wt-[0-9a-f]{8}([\\/]|$)'))
}

# Profile dir: STUDIO_CLIENT_CHANNEL=dev selects the dev profile
$suffix = if ($env:STUDIO_CLIENT_CHANNEL -eq 'dev') { '-Dev' } else { '' }
$base = if ($env:APPDATA) { Join-Path $env:APPDATA "StudioOS$suffix" } else { Join-Path $HOME ".config/studio-os$($suffix.ToLower())" }
$project = $null; $origin = $null
foreach ($f in Get-ChildItem (Join-Path $base 'workspaces') -Filter *.json -ErrorAction SilentlyContinue) {
    $w = Get-Content $f.FullName -Raw | ConvertFrom-Json
    $roots = @($w.roots.workspace_root) + @($w.roots.repo_roots | ForEach-Object { if ($_ -is [string]) { $_ } else { $_.path } })
    if ($roots | Where-Object { $_ -and (& $under $_) }) {
        $project = [string]$w.project_id; $origin = [string]$w.profile.server_origin; break
    }
}

# Unlinked repo declaring its project in AGENTS.md: link it (DEC-0285; the command needs the user's one-time consent)
$hint = $null
if (-not $project -and (Get-Command studio-client -ErrorAction SilentlyContinue)) {
    $common = git -C $cwd rev-parse --path-format=absolute --git-common-dir 2>$null
    $root = if ($common -and (Split-Path $common -Leaf) -eq '.git') { Split-Path $common -Parent } else { git -C $cwd rev-parse --show-toplevel 2>$null }
    if ($root -and (Test-Path (Join-Path $root 'AGENTS.md'))) {
        $link = studio-client workspaces auto-link --path $root --json 2>$null | ConvertFrom-Json
        if ($link.status -in 'linked', 'already_linked') { $project = [string]$link.project_id; $origin = [string]$link.server_origin }
        elseif ($link.status -and $link.status -ne 'no_project_id') { $hint = "lien auto: $($link.status)" + $(if ($link.status -eq 'no_consent') { ' (studio-client workspaces auto-link-consent grant)' }) }
    }
}

$harness = 'claude-code'
if (Get-ChildItem env: | Where-Object Name -like 'CODEX_*') { $harness = 'codex' }
elseif (Get-ChildItem env: | Where-Object Name -like 'OPENCODE*') { $harness = 'opencode' }
$agent = $null
if ($project -and (Get-Command studio-client -ErrorAction SilentlyContinue)) {
    if ($origin -and -not $env:STUDIO_CLIENT_API_BASE_URL) { $env:STUDIO_CLIENT_API_BASE_URL = $origin }
    $agent = (studio-client agents ensure --harness $harness --json 2>$null | ConvertFrom-Json).id
}

$parts = @(if ($project) { "project_id=$project" } else { $(if ($hint) { "projet non lié ($hint)" } else { 'projet non lié (studio-client workspaces register)' }) })
if ($agent) { $parts += "agent_id=$agent" }
$parts += "branche $(git -C $cwd branch --show-current)"
Write-Output ("Studio OS: " + ($parts -join ' | '))
exit 0
