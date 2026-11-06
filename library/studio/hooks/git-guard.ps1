# Studio OS hook git-guard (pre_tool, blocking). Exit 2 + stderr = blocked.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try { $p = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$cmd = $p.tool_input.command
if (-not $cmd) { $cmd = $p.args.command }
if (-not $cmd -or $cmd -notmatch '\bgit\b') { exit 0 }

function Block([string]$why) { [Console]::Error.WriteLine("git-guard: $why"); exit 2 }

if ($cmd -match 'git\s+reset\s+.*--hard') { Block 'reset --hard interdit (rule git-flow).' }
if ($cmd -cmatch 'git\s+branch\s+.*(-D\b|--delete\s+--force|-d\s+-f\b)') { Block 'branch -D interdit : git branch -d après fusion.' }
if ($cmd -match 'git\s+clean\s+.*-\w*f\w*d\w*x|git\s+clean\s+.*-\w*x\w*f') { Block 'clean -fdx interdit.' }
if ($cmd -match 'git\s+push\s+.*(--force\b|--force-with-lease|\s-f\b|\s\+\S)') { Block 'push forcé interdit.' }
if ($cmd -match 'git\s+push\s+(\S+\s+)?(HEAD:)?(master|main)\b') { Block 'push direct vers master/main interdit : passer par une PR.' }

if ($cmd -match 'git\s+commit\b') {
    $diff = git diff --cached -U0 2>$null
    $pat = '(?i)(-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9_-]{20,}|(password|secret|api[_-]?key|token)\s*[:=]\s*["''][^"'']{8,}["''])'
    $hits = $diff | Where-Object { $_ -like '+*' -and $_ -notlike '+++*' -and $_ -match $pat }
    if ($hits) { Block "secret probable dans l'index ($(@($hits).Count) ligne(s)) : retirer avant commit." }
}
exit 0
