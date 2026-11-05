# Studio OS hook stop-check (stop, advisory). Never blocks.
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$null = [Console]::In.ReadToEnd()
if (-not (git rev-parse --is-inside-work-tree 2>$null)) { exit 0 }
$notes = @()
$dirty = @(git status --porcelain).Count
if ($dirty) { $notes += "$dirty fichier(s) non commité(s)." }
$branch = git branch --show-current
$base = @('dev', 'master', 'main') | Where-Object { git rev-parse --verify --quiet "refs/heads/$_" } | Select-Object -First 1
if ($base) {
    $merged = git branch --merged $base --format '%(refname:short)' | Where-Object { $_ -match '^(task|hotfix)/' -and $_ -ne $branch }
    if ($merged) { $notes += "Branches fusionnées à nettoyer : $($merged -join ', ')." }
}
$wt = @(git worktree list --porcelain | Where-Object { $_ -like 'worktree *' }).Count - 1
if ($wt -gt 0) { $notes += "$wt worktree(s) secondaire(s) ouvert(s)." }
if ($branch -match '^(task|hotfix)/') { $notes += "Branche $branch : clore par un seul studio_handoff après merge et CI verte." }
if ($notes) { Write-Output ("stop-check: " + ($notes -join ' ')) }
exit 0
