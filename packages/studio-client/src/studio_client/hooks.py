from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MANAGED_MARKER = "Studio OS managed by setup-hooks"
AGENT_STORE_REL = Path(".claude") / "studio-agent.json"

_HOOK_PS_TEMPLATE = """# Studio OS — demarrage de session (__HARNESS_LABEL__).
# __MANAGED_MARKER__ (W2b/DEC-0100). Fichier d'integration Studio OS :
# safe a regenerer via `studio-client setup-hooks`. Fail-open : silencieux
# (aucune sortie, code 0) hors projet suivi. Toujours code 0. Aucun secret
# ici : seul l'agent_id (non secret) est persiste, le jeton machine reste
# keyring/env et n'est lu que par studio-client.
$ErrorActionPreference = 'Stop'
$OutputFormat = '__OUTPUT__'
try {
    $cwd = $null
    try {
        $raw = [Console]::In.ReadToEnd()
        if ($raw) { $cwd = ($raw | ConvertFrom-Json).cwd }
    } catch {}
    if (-not $cwd) { $cwd = (Get-Location).Path }

    $norm = {
        param($p) [IO.Path]::GetFullPath([string]$p).TrimEnd('\\', '/').Replace('/', '\\')
    }
    $here = & $norm $cwd
    $under = {
        param($root) $r = & $norm $root
        $here.Equals($r, 'OrdinalIgnoreCase') -or $here.StartsWith($r + '\\', 'OrdinalIgnoreCase')
    }
    $tracked = $false
    $projectInfo = $null
    $wsServerOrigin = $null

    $wsDir = Join-Path $env:APPDATA 'StudioOS\\workspaces'
    if (Test-Path -LiteralPath $wsDir) {
        foreach ($f in Get-ChildItem -LiteralPath $wsDir -Filter *.json) {
            $ws = Get-Content -LiteralPath $f.FullName -Raw | ConvertFrom-Json
            $paths = @()
            if ($ws.roots.workspace_root) { $paths += [string]$ws.roots.workspace_root }
            foreach ($rr in @($ws.roots.repo_roots)) {
                if ($rr -is [string]) { $paths += $rr }
                elseif ($rr.path) { $paths += [string]$rr.path }
            }
            foreach ($root in ($paths | Where-Object { $_ })) {
                if (& $under $root) {
                    $tracked = $true
                    $projectInfo = "project_id $($ws.project_id) (slug $($ws.project_slug))."
                    try { $wsServerOrigin = [string]$ws.profile.server_origin } catch {}
                    break
                }
            }
            if ($tracked) { break }
        }
    }

    $cfgDefault = Join-Path $env:APPDATA 'StudioOS\\config.toml'
    $envCfg = $env:STUDIO_CLIENT_CONFIG_FILE
    $configPath = if ($envCfg) { $envCfg } else { $cfgDefault }
    if (-not $tracked -and (Test-Path -LiteralPath $configPath)) {
        foreach ($line in Get-Content -LiteralPath $configPath) {
            $isRepo = $line -match '^\\s*(?:git_watch_repo_path|repo_path)\\s*=\\s*"([^"]+)"'
            if ($isRepo -and (& $under $Matches[1])) { $tracked = $true; break }
        }
    }
    if (-not $tracked) { exit 0 }

    $projText = 'project_id via studio_get_projects (slug du depot).'
    if ($projectInfo) { $projText = $projectInfo }
    $base = 'Projet suivi par Studio OS ; ' + $projText + ' Branches : skill studio-git-flow.'
    $agentPath = Join-Path $HOME '.claude\\studio-agent.json'
    $agentId = $null
    try {
        if (Test-Path -LiteralPath $agentPath) {
            $agentId = (Get-Content -LiteralPath $agentPath -Raw | ConvertFrom-Json).'__AGENT_KEY__'
        }
    } catch {}
    if (-not $agentId) {
        # W2 (DEC-0099) : assurer l'agent du harnais via studio-client (fail-open).
        try {
            if ($wsServerOrigin -and (Get-Command studio-client -ErrorAction SilentlyContinue)) {
                $env:STUDIO_CLIENT_API_BASE_URL = $wsServerOrigin
                $cmdOut = (& studio-client agents ensure --harness __HARNESS__ --json 2>$null)
                $ensured = ($cmdOut | ConvertFrom-Json)
                if ($ensured -and $ensured.id) {
                    $agentId = [string]$ensured.id
                    $doc = @{}
                    try {
                        $raw = Get-Content -LiteralPath $agentPath -Raw -ErrorAction Stop
                        $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
                        foreach ($p in $parsed.PSObject.Properties) { $doc[$p.Name] = $p.Value }
                    } catch {}
                    $doc['__AGENT_KEY__'] = $agentId
                    $docJson = ($doc | ConvertTo-Json -Compress)
                    $docJson | Set-Content -LiteralPath $agentPath -Encoding utf8
                }
            }
        } catch {}
    }
    $idSuffix = '(studio_start_session, studio_log_ai_work).'
    if ($OutputFormat -eq 'json') {
        $ctx = $base
        if ($agentId) { $ctx += " agent_id Studio OS de ce harness : $agentId $idSuffix" }
        $hookOut = @{ hookEventName = 'SessionStart'; additionalContext = $ctx }
        $envelope = @{ hookSpecificOutput = $hookOut }
        $envelope | ConvertTo-Json -Compress -Depth 4
    } else {
        $lines = @($base)
        if ($agentId) { $lines += "agent_id Studio OS de ce harness : $agentId $idSuffix" }
        else {
            $lines += "agent_id __HARNESS_LABEL__ manquant (hors ligne ou sans credential) :"
            $lines += 'le signaler en cloture, ne pas chercher de jeton.'
        }
        $lines | Write-Output
    }
} catch {
    exit 0
}
"""


@dataclass(frozen=True)
class HarnessSpec:
    """One supported harness: where its session-start hook lives (relative
    to the user's home), which `studio-agent.json` key it owns, and how the
    hook talks back (`text` for OpenCode's plugin, `json` envelope for
    Claude Code's SessionStart)."""

    harness: str
    label: str
    hook_rel: Path
    agent_key: str
    output: str
    config_markers: tuple[str, ...] = ()
    binaries: tuple[str, ...] = ()


HARNESSES: tuple[HarnessSpec, ...] = (
    HarnessSpec(
        harness="claude-code",
        label="Claude Code",
        hook_rel=Path(".claude") / "scripts" / "studio-session-start.ps1",
        agent_key="claude-code",
        output="json",
        config_markers=(".claude.json", ".claude/settings.json"),
        binaries=("claude",),
    ),
    HarnessSpec(
        harness="opencode",
        label="OpenCode",
        hook_rel=Path(".config") / "opencode" / "scripts" / "studio-session-start-opencode.ps1",
        agent_key="opencode",
        output="text",
        config_markers=(".config/opencode/opencode.jsonc", ".config/opencode/opencode.json"),
        binaries=("opencode",),
    ),
)


def render_hook(spec: HarnessSpec) -> str:
    """Render the versioned session-start hook for `spec`. Pure text: no
    secret, no absolute path, no network — the harness name and agent key
    are the only interpolations."""
    return (
        _HOOK_PS_TEMPLATE.replace("__HARNESS__", spec.harness)
        .replace("__HARNESS_LABEL__", spec.label)
        .replace("__AGENT_KEY__", spec.agent_key)
        .replace("__OUTPUT__", spec.output)
        .replace("__MANAGED_MARKER__", MANAGED_MARKER)
    )


def is_managed(path: Path) -> bool:
    try:
        return MANAGED_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def detect_harnesses(home: Path, path_dirs: tuple[str, ...]) -> list[HarnessSpec]:
    """Harnesses considered installed under `home`: a known config marker or
    binary is present. Pure local check, never touches user/global account
    files (DEC-0096 boundary)."""
    found: list[HarnessSpec] = []
    path_set = {p.lower() for p in path_dirs}
    for spec in HARNESSES:
        if any((home / marker).exists() for marker in spec.config_markers):
            found.append(spec)
            continue
        if any(
            any((Path(d) / f"{binary}{ext}").is_file() for ext in ("", ".exe", ".cmd", ".bat"))
            for d in path_set
            for binary in spec.binaries
        ):
            found.append(spec)
    return found


@dataclass
class DeployReport:
    harness: str
    target: str
    status: str
    detail: str = ""


@dataclass
class DeployResult:
    reports: list[DeployReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "deployed": [
                {"harness": r.harness, "target": r.target, "status": r.status, "detail": r.detail}
                for r in self.reports
            ]
        }


def deploy_hooks(
    home: Path,
    specs: list[HarnessSpec],
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> DeployResult:
    """Write missing session-start hooks under `home`. Idempotent: an
    existing managed hook is left untouched (`unchanged`); a foreign file is
    never overwritten unless `overwrite=True` (`needs-overwrite` otherwise).
    `dry_run` writes nothing. Atomic replace per file; no secret is ever
    written (the template carries none)."""
    result = DeployResult()
    for spec in specs:
        target = home / spec.hook_rel
        if target.is_file():
            if is_managed(target) and not overwrite:
                result.reports.append(DeployReport(spec.harness, str(target), "unchanged"))
                continue
            if not is_managed(target) and not overwrite:
                result.reports.append(
                    DeployReport(
                        spec.harness,
                        str(target),
                        "needs-overwrite",
                        "foreign hook file present; rerun with --overwrite",
                    )
                )
                continue
        if dry_run:
            result.reports.append(
                DeployReport(
                    spec.harness,
                    str(target),
                    "would-deploy" if not target.is_file() else "would-overwrite",
                )
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(render_hook(spec), encoding="utf-8")
        os.replace(tmp, target)
        result.reports.append(
            DeployReport(spec.harness, str(target), "overwritten" if overwrite else "deployed")
        )
    return result
