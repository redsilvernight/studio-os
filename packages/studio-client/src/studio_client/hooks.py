from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MANAGED_MARKER = "Studio OS managed by setup-hooks"
AGENT_STORE_REL = Path(".claude") / "studio-agent.json"
GUARD_REL = Path(".claude") / "scripts" / "studio-git-guard.ps1"

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
    $modelRef = $null
    try {
        $raw = [Console]::In.ReadToEnd()
        if ($raw) {
            $payload = ($raw | ConvertFrom-Json)
            $cwd = $payload.cwd
            $modelRef = $payload.model
        }
    } catch {}
    if (-not $cwd) { $cwd = (Get-Location).Path }

    $norm = {
        param($p) [IO.Path]::GetFullPath([string]$p).TrimEnd('\\', '/')
    }
    $here = & $norm $cwd
    $sep = [IO.Path]::DirectorySeparatorChar
    $under = {
        param($root)
        $r = & $norm $root
        if ($here.Equals($r, 'OrdinalIgnoreCase')) { return $true }
        if ($here.StartsWith($r + $sep, 'OrdinalIgnoreCase')) { return $true }
        $parent = [IO.Path]::GetDirectoryName($r)
        $leaf = [IO.Path]::GetFileName($r)
        if (-not $parent -or -not $leaf) { return $false }
        $prefix = $parent + $sep + $leaf + '-wt-'
        if (-not $here.StartsWith($prefix, 'OrdinalIgnoreCase')) { return $false }
        $rest = $here.Substring($prefix.Length)
        $cut = $rest.IndexOfAny([char[]]@('\\', '/'))
        if ($cut -ge 0) { $rest = $rest.Substring(0, $cut) }
        return [bool]($rest -match '^[0-9a-fA-F]{8}$')
    }
    $tracked = $false
    $projectInfo = $null
    $wsServerOrigin = $null

    $isWin = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
    $dev = $false
    if ($env:STUDIO_CLIENT_CHANNEL) { $dev = $env:STUDIO_CLIENT_CHANNEL -eq 'dev' }
    $profileDir = $null
    if ($isWin) {
        $appData = $env:APPDATA
        if (-not $appData) { $appData = Join-Path $HOME 'AppData\\Roaming' }
        $devDir = Join-Path $appData 'StudioOS-Dev'
        $prodDir = Join-Path $appData 'StudioOS'
        if (-not $env:STUDIO_CLIENT_CHANNEL) {
            $dev = (Test-Path -LiteralPath $devDir) -and -not (Test-Path -LiteralPath $prodDir)
        }
        $profileDir = if ($dev) { $devDir } else { $prodDir }
    } else {
        $xdg = $env:XDG_CONFIG_HOME
        if (-not $xdg) { $xdg = Join-Path $HOME '.config' }
        $devDir = Join-Path $xdg 'studio-os-dev'
        $prodDir = Join-Path $xdg 'studio-os'
        if (-not $env:STUDIO_CLIENT_CHANNEL) {
            $dev = (Test-Path -LiteralPath $devDir) -and -not (Test-Path -LiteralPath $prodDir)
        }
        $profileDir = if ($dev) { $devDir } else { $prodDir }
    }
    $wsDir = Join-Path $profileDir 'workspaces'
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

    $cfgDefault = Join-Path $profileDir 'config.toml'
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
    # Le cache est scope par origine serveur : un id d'agent n'a de sens que sur
    # le serveur qui l'a emis. Sans cela, un lancement sur une autre origine
    # reutilise un id etranger, studio_start_work echoue et l'agent s'enregistre
    # a nouveau a chaque lancement.
    $originKey = if ($wsServerOrigin) { $wsServerOrigin } else { 'default' }
    # Claude Code : le MCP s'authentifie avec le credential dedie de l'outil
    # (DEC-0104), ecrit dans ~/.claude.json. L'agent doit appartenir a cette
    # machine, sinon studio_start_work repond actor_not_owned : `agents ensure`
    # reprend donc ce credential (environnement du hook seulement), et le cache
    # est cle par son empreinte pour s'invalider au renouvellement.
    if ('__HARNESS__' -eq 'claude-code' -and $wsServerOrigin) {
        try {
            $cjPath = Join-Path $HOME '.claude.json'
            $cj = Get-Content -LiteralPath $cjPath -Raw -ErrorAction Stop | ConvertFrom-Json
            $auth = [string]$cj.mcpServers.'studio-os'.headers.Authorization
            if ($auth -match '^Bearer\\s+(\\S+)$' -and $Matches[1] -notmatch '^\\$\\{') {
                $mcpToken = $Matches[1]
                $env:STUDIO_CLIENT_MACHINE_TOKEN = $mcpToken
                $env:STUDIO_CLIENT_MACHINE_TOKEN_ORIGIN = $wsServerOrigin
                $sha = [Security.Cryptography.SHA256]::Create()
                $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($mcpToken))
                $fp = [BitConverter]::ToString($bytes).Replace('-', '').Substring(0, 8).ToLower()
                $originKey = "${originKey}#$fp"
            }
        } catch {}
    }
    $agentId = $null
    $agentLabel = 'ce harness'
    # Identite = (harness, provider, modele) des que le harnais expose son
    # modele (AIB L2) ; sinon repli sur l'agent du harnais (DEC-0099). Le bloc
    # modele est commun aux sorties texte et JSON.
__MODEL_BLOCK__
    if (-not $agentId) {
        $baseAgentKey = "__AGENT_KEY__:${originKey}"
        try {
            if (Test-Path -LiteralPath $agentPath) {
                $storedAgent = Get-Content -LiteralPath $agentPath -Raw | ConvertFrom-Json
                $agentId = $storedAgent.$baseAgentKey
            }
        } catch {}
        if (-not $agentId) {
            # W2 (DEC-0099) : assurer l'agent du harnais via studio-client (fail-open).
            try {
                $haveClient = Get-Command studio-client -ErrorAction SilentlyContinue
                if ($wsServerOrigin -and $haveClient) {
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
                        $doc[$baseAgentKey] = $agentId
                        $docJson = ($doc | ConvertTo-Json -Compress)
                        $docJson | Set-Content -LiteralPath $agentPath -Encoding utf8
                    }
                }
            } catch {}
        }
    }
    $idSuffix = '(studio_start_work, studio_log_ai_work).'
    if ($OutputFormat -eq 'json') {
        $ctx = $base
        if ($agentId) { $ctx += " agent_id Studio OS de $agentLabel : $agentId $idSuffix" }
        $hookOut = @{ hookEventName = 'SessionStart'; additionalContext = $ctx }
        $envelope = @{ hookSpecificOutput = $hookOut }
        $envelope | ConvertTo-Json -Compress -Depth 4
    } else {
        $lines = @($base)
        if ($agentId) { $lines += "agent_id Studio OS de $agentLabel : $agentId $idSuffix" }
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

_MODEL_BLOCK_PS = """
    # Bloc modele (AIB L2, toutes sorties) : un agent par couple
    # (harness, provider, modele), jamais l'agent du harnais en plus. Cache
    # local "__AGENT_KEY__:<origin>:<provider>/<model>" dans studio-agent.json,
    # resolu via POST /agents/ensure (idempotent, stable_key dedie), fail-open.
    if ($modelRef) {
        $cacheKey = "__AGENT_KEY__:${originKey}:$modelRef"
        $modelAgentId = $null
        try {
            if (Test-Path -LiteralPath $agentPath) {
                $stored = Get-Content -LiteralPath $agentPath -Raw | ConvertFrom-Json
                $modelAgentId = $stored."$cacheKey"
            }
        } catch {}
        if (-not $modelAgentId) {
            try {
                $haveClient = Get-Command studio-client -ErrorAction SilentlyContinue
                if ($wsServerOrigin -and $haveClient) {
                    $env:STUDIO_CLIENT_API_BASE_URL = $wsServerOrigin
                    $prov = $null
                    $mid = [string]$modelRef
                    $slash = $mid.IndexOf('/')
                    if ($slash -ge 0) {
                        $prov = $mid.Substring(0, $slash)
                        $mid = $mid.Substring($slash + 1)
                    }
                    $ensureArgs = @(
                        'agents', 'ensure',
                        '--harness', '__HARNESS__',
                        '--model', $mid,
                        '--stable-key', "agents-ensure-__HARNESS__:$modelRef",
                        '--json'
                    )
                    if ($prov) { $ensureArgs += @('--provider', $prov) }
                    $ensured = (& studio-client @ensureArgs 2>$null | ConvertFrom-Json)
                    if ($ensured -and $ensured.id) {
                        $modelAgentId = [string]$ensured.id
                        $doc = @{}
                        try {
                            $rawDoc = Get-Content -LiteralPath $agentPath -Raw -ErrorAction Stop
                            $parsedDoc = $rawDoc | ConvertFrom-Json -ErrorAction Stop
                            foreach ($p in $parsedDoc.PSObject.Properties) {
                                $doc[$p.Name] = $p.Value
                            }
                        } catch {}
                        $doc[$cacheKey] = $modelAgentId
                        $docJson = $doc | ConvertTo-Json -Compress
                        $docJson | Set-Content -LiteralPath $agentPath -Encoding utf8
                    }
                }
            } catch {}
        }
        if ($modelAgentId) {
            $agentId = $modelAgentId
            $agentLabel = "ce harness/modele ($modelRef)"
        }
    }
"""

_GUARD_PS_TEMPLATE = """# __MANAGED_MARKER__ (L1/setup-hooks). Fichier d'integration Studio OS :
# safe a regenerer via `studio-client setup-hooks`. Bloque un `git commit`
# direct sur une branche protegee (roadmap/*, phase/*, ou master/main avec une
# branche `roadmap`) ; les fusions par git merge apres approbation passent.
# Sortie 2 = commande bloquee, 0 = autorisee ; fail-open (jamais 1). Aucun
# secret, aucun chemin absolu.
$ErrorActionPreference = 'Stop'
try {
    $in = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $cmd = [string]$in.tool_input.command
    $commitRe = '(^|[;&|\\r\\n]|&&|\\|\\|)' +
        '\\s*(rtk\\s+)?git(\\s+-[Cc]\\s+\\S+)*\\s+commit\\b'
    if ($cmd -notmatch $commitRe) { exit 0 }

    $cwd = if ($in.cwd) { $in.cwd } else { (Get-Location).Path }
    Push-Location -LiteralPath $cwd
    try {
        $branch = (git branch --show-current 2>$null)
        if (-not $branch) { exit 0 }
        git rev-parse -q --verify MERGE_HEAD *> $null
        if ($LASTEXITCODE -eq 0) { exit 0 }
        $protected = $branch -like 'roadmap/*' -or $branch -like 'phase/*'
        if (-not $protected -and $branch -in @('master', 'main')) {
            $roadmapRef = git for-each-ref --count=1 --format='%(refname)' `
                refs/heads/roadmap 2>$null
            $protected = [bool]$roadmapRef
        }
    } finally {
        Pop-Location
    }
    if ($protected) {
        $msg = "studio-git-guard: commit direct interdit sur '$branch'. " +
            "Travailler sur une branche task/* (skill studio-git-flow) ; " +
            "les fusions se font par git merge apres approbation."
        [Console]::Error.WriteLine($msg)
        exit 2
    }
    exit 0
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
    register_hint: str = ""


HARNESSES: tuple[HarnessSpec, ...] = (
    HarnessSpec(
        harness="claude-code",
        label="Claude Code",
        hook_rel=Path(".claude") / "scripts" / "studio-session-start.ps1",
        agent_key="claude-code",
        output="json",
        config_markers=(".claude.json", ".claude/settings.json"),
        binaries=("claude",),
        register_hint=(
            "register in .claude/settings.json under hooks.SessionStart "
            '({{"matcher": "startup|resume", "hooks": [{{"type": "command", '
            '"command": "pwsh -NoProfile -File \\"{target}\\"", "timeout": 30}}]}})'
        ),
    ),
    HarnessSpec(
        harness="opencode",
        label="OpenCode",
        hook_rel=Path(".config") / "opencode" / "scripts" / "studio-session-start-opencode.ps1",
        agent_key="opencode",
        output="text",
        config_markers=(".config/opencode/opencode.jsonc", ".config/opencode/opencode.json"),
        binaries=("opencode",),
        register_hint=(
            "session wiring is the managed studio-os.js plugin (deployed by "
            "setup-hooks next to the script); restart OpenCode to load it"
        ),
    ),
    HarnessSpec(
        harness="codex",
        label="Codex",
        hook_rel=Path(".codex") / "studio-session-start-codex.ps1",
        agent_key="codex",
        output="text",
        config_markers=(".codex/config.toml", ".codex/hooks.json"),
        binaries=("codex",),
        register_hint=(
            "register in .codex/hooks.json under hooks.SessionStart "
            '({{"matcher": "startup|resume", "hooks": [{{"type": "command", '
            '"command": "pwsh -NoProfile -File \\"{target}\\"", "timeout": 30}}]}})'
        ),
    ),
)


def render_hook(spec: HarnessSpec) -> str:
    """Render the versioned session-start hook for `spec`. Pure text: no
    secret, no absolute path — the harness name, agent key, output format,
    managed marker and the per-model agent block are the only interpolations.
    The model block reads/writes only the non-secret agent id store; any
    network call goes through `studio-client`."""
    return (
        _HOOK_PS_TEMPLATE.replace("__MODEL_BLOCK__", _MODEL_BLOCK_PS)
        .replace("__HARNESS__", spec.harness)
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


def render_guard() -> str:
    """Render the versioned git guard. Pure text: only the managed marker is
    interpolated — no secret, no absolute path, no machine-specific value."""
    return _GUARD_PS_TEMPLATE.replace("__MANAGED_MARKER__", MANAGED_MARKER)


def guard_state(home: Path) -> str:
    """State of the git guard the harnesses call: `guard-missing`,
    `guard-managed` or `guard-foreign`."""
    target = home / GUARD_REL
    if not target.is_file():
        return "guard-missing"
    return "guard-managed" if is_managed(target) else "guard-foreign"


def deploy_guard(
    home: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> DeployResult:
    """Write the managed git guard under `home`. Same semantics as
    `deploy_hooks`: idempotent (`unchanged`), a foreign file is never
    overwritten without `overwrite=True` (`needs-overwrite`), `dry_run`
    writes nothing, atomic replace, no secret written."""
    result = DeployResult()
    target = home / GUARD_REL
    if target.is_file():
        if is_managed(target) and not overwrite:
            result.reports.append(DeployReport("git-guard", str(target), "unchanged"))
            return result
        if not is_managed(target) and not overwrite:
            result.reports.append(
                DeployReport(
                    "git-guard",
                    str(target),
                    "needs-overwrite",
                    "foreign guard file present; rerun with --overwrite",
                )
            )
            return result
    if dry_run:
        result.reports.append(
            DeployReport(
                "git-guard",
                str(target),
                "would-deploy" if not target.is_file() else "would-overwrite",
            )
        )
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(render_guard(), encoding="utf-8")
    os.replace(tmp, target)
    result.reports.append(
        DeployReport("git-guard", str(target), "overwritten" if overwrite else "deployed")
    )
    return result
