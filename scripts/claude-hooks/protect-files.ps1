# Claude Code PreToolUse (Edit|Write|MultiEdit|NotebookEdit): blocks edits to
# secrets, generated projections and generated artifacts. Exit 2 = blocked,
# stderr is shown to Claude. Fail-open on malformed input.
$ErrorActionPreference = 'Stop'
try {
    $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $path = [string]($payload.tool_input.file_path ?? $payload.tool_input.notebook_path)
} catch { exit 0 }
if (-not $path) { exit 0 }

try {
    $root = [string]($env:CLAUDE_PROJECT_DIR ?? $payload.cwd)
    $full = [IO.Path]::GetFullPath($path)
    $rel = $full
    if ($root) {
        $rootFull = [IO.Path]::GetFullPath($root).TrimEnd('\', '/')
        if ($full.StartsWith($rootFull + [IO.Path]::DirectorySeparatorChar, 'OrdinalIgnoreCase')) {
            $rel = $full.Substring($rootFull.Length + 1)
        }
    }
    $rel = $rel.Replace('\', '/')
} catch { exit 0 }

$rules = @(
    @{ re = '(^|/)\.env(\.[^/]*)?$'; skip = '\.example$'
       why = 'secret file (.env*). Edit it yourself; only *.env.example is editable here.' }
    @{ re = '^\.(claude|codex|opencode)/(agents|rules|skills)/'
       why = 'harness projection. Edit the canonical source under .agents/ (definitions, rules, skills), then regenerate. Agents: `uv run studio-client adapters export --from-canonical --adapter <claude-code|codex|opencode> --stable-key <key> --out-dir . --overwrite`; skills: verbatim copy of .agents/skills/<key>/SKILL.md; check with `uv run studio-client adapters check`.' }
    @{ re = '^dashboard/src/openapi-schema\.ts$'
       why = 'generated from the API. Run `npm run openapi` in dashboard/ (skill openapi-sync).' }
    @{ re = '^dashboard/openapi\.json$'
       why = 'exported from the backend. Run `npm run openapi:export` in dashboard/ (skill openapi-sync).' }
    @{ re = '^docs/(DEC_EXPORT\.json|DECISIONS\.md|decisions/)'
       why = 'decision export generated from the server (scripts/dec_export.py). Record decisions with studio_add_decision.' }
)
foreach ($r in $rules) {
    if ($rel -match $r.re -and -not ($r.skip -and $rel -match $r.skip)) {
        [Console]::Error.WriteLine("Blocked edit of ${rel}: $($r.why)")
        exit 2
    }
}
exit 0
