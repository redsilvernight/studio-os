"""Versioned OpenCode plugin (follow-up of setup-hooks/Codex, DEC-0100):
`studio-os.js` deployed managed under `<home>/.config/opencode/plugins/`,
so a fresh machine gets the session-context injection and the git-guard
wiring without hand-copying a plugin.

Scope notes, read before extending:
- Only the plugin file itself is written (DEC-0096 boundary): never
  `opencode.json[c]`, never user account configs. Enabling = the file
  being present; OpenCode loads `plugins/*.js` on start.
- Paths are interpolated at deploy time from `home` (no machine-specific
  absolute path in the template).
- The plugin calls two scripts: the managed session-start hook (deployed
  by `setup-hooks` alongside) and `studio-git-guard.ps1`, which is still
  hand-maintained — deploy reports its state (`guard-managed`,
  `guard-missing`, `guard-foreign`) but never writes it. Versioning the
  guard is a separate task.
- Per-model agent lines (`harness/modele`) are read opportunistically:
  with a managed session script they are simply absent (fail-open) until
  the model protocol lands in the hook template (separate task).
"""

from __future__ import annotations

import os
from pathlib import Path

from studio_client.hooks import (
    HARNESSES,
    MANAGED_MARKER,
    DeployReport,
    DeployResult,
    is_managed,
)

PLUGIN_REL = Path(".config") / "opencode" / "plugins" / "studio-os.js"
GUARD_REL = Path(".claude") / "scripts" / "studio-git-guard.ps1"

_PLUGIN_JS_TEMPLATE = """// Studio OS — plugin global OpenCode.
// __MANAGED_MARKER__ (L1/setup-hooks). Fichier d'integration Studio OS :
// safe a regenerer via `studio-client setup-hooks`. Fail-open.
//
// Transposition des hooks Claude Code, sans les recopier :
// (b) avant chaque commande bash -> __GUARD_SCRIPT__
//     (appel direct, stdin JSON {"tool_input":{"command"},"cwd"} ; sortie 2 = bloquer).
// (a) au demarrage -> __SESSION_SCRIPT__ (deploys par setup-hooks),
//     contexte texte ajoute au system prompt (project_id, agent_id cle "opencode").
//
// Tout est fail-open : si pwsh ou un script manque, la session continue sans garde-fou
// (les memes regles restent dans AGENTS.md global en repli manuel).
import { spawnSync } from "node:child_process";

const GUARD_SCRIPT = "__GUARD_SCRIPT__";
const SESSION_SCRIPT = "__SESSION_SCRIPT__";
const SHELLS = ["pwsh", "powershell"];

function runScript(script, payload) {
  const input = JSON.stringify(payload);
  for (const exe of SHELLS) {
    try {
      const r = spawnSync(exe, ["-NoProfile", "-File", script], { input, encoding: "utf8" });
      if (r.error) continue;
      const status = r.status === null ? 0 : r.status;
      return { exit: status, stdout: r.stdout || "", stderr: r.stderr || "" };
    } catch {
      continue;
    }
  }
  return { exit: 0, stdout: "", stderr: "", skipped: true };
}

export const StudioOS = async ({ client, directory }) => {
  const cwd = directory;
  let cachedContext = null;
  const agentCache = new Map();

  async function sessionContext() {
    if (cachedContext !== null) return cachedContext;
    cachedContext = "";
    try {
      const r = runScript(SESSION_SCRIPT, { cwd });
      if (!r.skipped && r.exit === 0 && r.stdout.trim()) cachedContext = r.stdout.trim();
    } catch {
      cachedContext = "";
    }
    if (cachedContext) {
      try {
        await client.app.log({
          body: { service: "studio-os", level: "info", message: "Studio OS context injected" },
        });
      } catch {
        // Journal indisponible : le contexte reste injecte via le system prompt.
      }
    }
    return cachedContext;
  }

  return {
    event: async ({ event }) => {
      try {
        if (event && event.type === "session.created") await sessionContext();
      } catch {
        // Fail-open : aucun blocage de session.
      }
    },
    "experimental.chat.system.transform": async (input, output) => {
      const ctx = await sessionContext();
      if (
        ctx &&
        output &&
        Array.isArray(output.system) &&
        !output.system.some((s) => typeof s === "string" && s.includes("Studio OS"))
      ) {
        output.system.push(ctx);
      }
      // Agent par modele : input.model = { id, providerID }. Resolu une fois
      // par (session, modele) via le script (cache fichier + ensure API),
      // fail-open : en cas d'echec, rien n'est injecte.
      try {
        const m = input && input.model;
        const modelRef =
          m && typeof m.id === "string" && typeof m.providerID === "string"
            ? `${m.providerID}/${m.id}`
            : null;
        if (modelRef && output && Array.isArray(output.system)) {
          const sid = (input && input.sessionID) || "noid";
          const key = `${sid}::${modelRef}`;
          if (!agentCache.has(key)) {
            let line = "";
            try {
              const r = runScript(SESSION_SCRIPT, { cwd, model: modelRef });
              if (!r.skipped && r.exit === 0 && r.stdout.trim()) {
                line = r.stdout
                  .trim()
                  .split(/\\r?\\n/)
                  .filter((l) => l.includes("harness/modele"))
                  .join("\\n");
              }
            } catch {
              line = "";
            }
            agentCache.set(key, line);
          }
          const cached = agentCache.get(key);
          if (
            cached &&
            !output.system.some((s) => typeof s === "string" && s.includes("harness/modele"))
          ) {
            output.system.push(cached);
          }
        }
      } catch {
        // Fail-open : aucun blocage de completion.
      }
    },
    "tool.execute.before": async (input, output) => {
      if (!input || input.tool !== "bash") return;
      const command = output && output.args ? output.args.command : undefined;
      if (typeof command !== "string" || !command) return;
      let r;
      try {
        r = runScript(GUARD_SCRIPT, { tool_input: { command }, cwd });
      } catch {
        return; // fail-open
      }
      if (r && !r.skipped && r.exit === 2) {
        const detail = (r.stderr || "").trim();
        throw new Error(detail || "studio-git-guard: commit direct interdit sur cette branche.");
      }
    },
  };
};
"""

_OPENCODE_SPEC = next(spec for spec in HARNESSES if spec.harness == "opencode")


def plugin_target(home: Path) -> Path:
    return home / PLUGIN_REL


def render_plugin(home: Path) -> str:
    """Render the versioned plugin for `home`: the only interpolations are
    the managed marker and the two script paths (forward slashes — pwsh
    accepts them). No secret, no machine-specific absolute path baked in."""
    session_script = (home / _OPENCODE_SPEC.hook_rel).as_posix()
    guard_script = (home / GUARD_REL).as_posix()
    return (
        _PLUGIN_JS_TEMPLATE.replace("__MANAGED_MARKER__", MANAGED_MARKER)
        .replace("__GUARD_SCRIPT__", guard_script)
        .replace("__SESSION_SCRIPT__", session_script)
    )


def guard_state(home: Path) -> str:
    """State of the hand-maintained guard script the plugin calls: the
    plugin never writes it (separate versioning task), it only reports."""
    target = home / GUARD_REL
    if not target.is_file():
        return "guard-missing"
    return "guard-managed" if is_managed(target) else "guard-foreign"


def deploy_plugin(
    home: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> DeployResult:
    """Write the managed plugin under `home`. Same semantics as
    `hooks.deploy_hooks`: idempotent (`unchanged`), a foreign file is never
    overwritten without `overwrite=True` (`needs-overwrite`), `dry_run`
    writes nothing, atomic replace, no secret ever written. The guard state
    rides in `detail` (informational only)."""
    result = DeployResult()
    target = plugin_target(home)
    detail = guard_state(home)
    if target.is_file():
        if is_managed(target) and not overwrite:
            result.reports.append(DeployReport("opencode-plugin", str(target), "unchanged", detail))
            return result
        if not is_managed(target) and not overwrite:
            result.reports.append(
                DeployReport(
                    "opencode-plugin",
                    str(target),
                    "needs-overwrite",
                    f"foreign plugin file present; rerun with --overwrite ({detail})",
                )
            )
            return result
    if dry_run:
        result.reports.append(
            DeployReport(
                "opencode-plugin",
                str(target),
                "would-deploy" if not target.is_file() else "would-overwrite",
                detail,
            )
        )
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(render_plugin(home), encoding="utf-8")
    os.replace(tmp, target)
    result.reports.append(
        DeployReport(
            "opencode-plugin", str(target), "overwritten" if overwrite else "deployed", detail
        )
    )
    return result
