"""Native CLI trials; only the test MCP is configured, no personal config writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from validate import PYTHON, ROOT, RUNTIME, TRACE, environment, redact, save


async def supplied_context(
    env: dict[str, str], fixture: dict[str, Any], harness: str
) -> dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with stdio_client(
        StdioServerParameters(
            command=str(PYTHON), args=["-m", "studio_mcp.server"], env=env, cwd=str(RUNTIME)
        )
    ) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            arguments = {
                "project_id": fixture["project_id"],
                "task_id": fixture["tasks"][harness]["provided"],
                "objective": "Audit de cette tâche isolée",
                "limit": 1,
                "max_chars": 4000,
            }
            result = await client.call_tool("studio_prepare_context", arguments)
            context = result.structured_content or json.loads(result.content[0].text)
            context = context.get("result", context)
            cached = await client.call_tool(
                "studio_prepare_context",
                {
                    **arguments,
                    "known_ids": {context["task"]["id"]: context["task"]["content_hash"]},
                },
            )
            cached_value = cached.structured_content or json.loads(cached.content[0].text)
            cached_value = cached_value.get("result", cached_value)
            save(
                f"provided-context-{harness}.json",
                {"arguments": arguments, "context": context, "cache_response": cached_value},
            )
            assert cached_value["task"].get("unchanged") is True, cached_value["task"]
            return context


def prepare(harness: str) -> tuple[Path, dict[str, str], dict[str, Any]]:
    workspace = Path(tempfile.mkdtemp(prefix=f"studio-p15-{harness}-"))
    env = environment()
    env["STUDIO_MCP_MACHINE_TOKEN"] = (RUNTIME / "machine-token.txt").read_text()
    fixture = json.loads((TRACE / "fixture.json").read_text())
    for path in (
        ".agents/skills/studio-task",
        ".agents/skills/studio-context",
        ".agents/skills/studio-handoff",
        ".agents/rules",
    ):
        shutil.copytree(ROOT / path, workspace / path)
    for directory in (".claude", ".codex", ".opencode"):
        for part in ("agents", "skills"):
            source = ROOT / directory / part
            if source.exists():
                (workspace / directory / part).mkdir(parents=True, exist_ok=True)
                selected = (
                    ("studio-task", "studio-context", "studio-handoff")
                    if part == "skills"
                    else (
                        "contract-guardian",
                        "dashboard-a11y",
                        "migration-reviewer",
                        "studio-architect",
                        "studio-tester",
                        "sync-debugger",
                    )
                )
                for item in source.iterdir():
                    if item.stem in selected:
                        if item.is_dir():
                            shutil.copytree(item, workspace / directory / part / item.name)
                        else:
                            shutil.copy2(item, workspace / directory / part / item.name)
    protocol = (ROOT / ".agents/rules/studio-protocol.md").read_text()
    for name in ("AGENTS.md", "CLAUDE.md"):
        (workspace / name).write_text(
            protocol
            + (
                "\nUse the canonical studio-task skill for Studi'OS work. Only "
                "isolated fixture data is authorized. Read-only local commands are"
                " allowed exclusively for files in this fixture. Never use a "
                "network destination or MCP other than p15. No production project "
                "or outside-fixture file is authorized.\n"
            )
        )
    if harness != "codex":
        subprocess.run(["git", "init", "--quiet", str(workspace)], check=True, capture_output=True)
    (workspace / "receipt.txt").write_text(
        "P15 validation fixture: read this file and report its SHA256.\n"
    )
    mcp = {"command": str(PYTHON), "args": ["-m", "studio_mcp.server"]}
    (workspace / "mcp.json").write_text(json.dumps({"mcpServers": {"p15": mcp}}))
    save(
        f"workspace-{harness}.json",
        {
            "workspace": str(workspace),
            "copied_roles": sorted(
                p.name for p in (workspace / f".{harness}" / "agents").glob("*")
            ),
            "mcp": {"p15": mcp},
            "env_keys": sorted(k for k in env if k.startswith("STUDIO_")),
        },
    )
    return workspace, env, fixture


def run(harness: str, scenario: str, label: str = "") -> None:
    workspace, env, fixture = prepare(harness)
    ids = (
        f"Environment: project_id={fixture['project_id']}, "
        f"task_id={fixture['tasks'][harness][scenario]}, "
        f"owned agent_id={fixture['agents'][harness]}."
    )
    prompts = {
        "readonly": (
            "Fais un audit strictement en lecture seule de cette tâche et "
            "rends un diagnostic court. Ne crée ni session, tâche, claim, "
            "décision ni handoff. Aucun fichier à changer."
        ),
        "tracked": (
            "Prends en charge cette tâche d'audit suivie : vérifie dans sa "
            "description qu'elle désigne bien une fixture isolée sans donnée "
            "de production. Consigne une preuve vérifiable puis transmets le "
            "travail avec un état honnête. Aucun fichier ni code à modifier. "
            "Termine cette unité si ses vérifications sont réussies."
        ),
        "failed": (
            "Reprends cette tâche suivie. Le contrôle obligatoire fourni a "
            "échoué : commande verify-receipt, exit_code=1, résultat "
            "CHECKSUM_MISMATCH. Prépare une transmission avec ce résultat et "
            "l'état approprié. Ne relance pas de commande et ne corrige aucun "
            "fichier."
        ),
        "provided": (
            "Le dossier serveur frais et complet pour ce diagnostic est fourni"
            " ci-dessous, contenu conservé avec ses content_hash. Fais "
            "uniquement un diagnostic court des limites de cette tâche, en "
            "lecture seule, à partir de ce dossier. Aucun travail à démarrer "
            "ni fichier à lire."
        ),
    }
    readonly_variants = {
        "p16-e04-1": (
            "Passe en revue cette tâche comme un audit d'observation. Résume son état et son "
            "périmètre; "
            "aucune écriture ni prise en charge n'est autorisée."
        ),
        "p16-e04-2": (
            "Fais un contrôle bref de cette tâche en lecture seule. Observe uniquement les "
            "informations "
            "déjà enregistrées et ne change aucun état."
        ),
        "p16-e04-3": (
            "Évalue cette tâche pour un audit readonly et donne les constats utiles. Ne démarre "
            "pas de "
            "travail et n'enregistre aucune modification."
        ),
        "p16-e04-r2-1": (
            "Vérifie cette tâche en mode observation seulement. Donne un bref constat sur son état, "
            "sans ouvrir de session ni écrire."
        ),
        "p16-e04-r2-2": (
            "Fais une revue readonly de cette tâche et résume ce qui est établi. Ne prends pas la "
            "tâche en charge et ne change rien."
        ),
        "p16-e04-r2-3": (
            "Observe les informations de cette tâche pour un audit court. Garde l'opération sans "
            "écriture et sans démarrage de travail."
        ),
    }
    if scenario == "readonly" and label in readonly_variants:
        prompts["readonly"] = readonly_variants[label]
    prompt = ids + "\n" + prompts[scenario]
    if scenario == "provided":
        prompt += "\n" + json.dumps(
            asyncio.run(supplied_context(env, fixture, harness)), ensure_ascii=False
        )
    run_id = f"{harness}-{scenario}" + (f"-{label}" if label else "")
    if harness == "claude":
        command = [
            shutil.which("claude") or "claude",
            "-p",
            prompt,
            "--setting-sources",
            "project",
            "--settings",
            '{"disableAllHooks":true}',
            "--strict-mcp-config",
            "--mcp-config",
            str(workspace / "mcp.json"),
            "--tools",
            "Read,Skill",
            "--allowedTools",
            "Read,Skill,mcp__p15",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--max-budget-usd",
            "1",
        ]
    elif harness == "codex":
        command = [
            shutil.which("codex") or "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "-c",
            "features.apps=false",
            "-c",
            "features.plugins=false",
            "-c",
            "features.memories=false",
            "-c",
            f"mcp_servers.p15.command={json.dumps(str(PYTHON))}",
            "-c",
            'mcp_servers.p15.args=["-m","studio_mcp.server"]',
            "-c",
            'mcp_servers.p15.env_vars=["STUDIO_DATABASE_URL","STUDIO_MCP_MACHINE_TOKEN","STUDIO_ENVIRONMENT","STUDIO_MCP_TOOL_PROFILE"]',
            prompt,
        ]
        if label == "approved":
            command[-1:-1] = [
                "-c",
                "mcp_servers.p15.required=true",
                "-c",
                'mcp_servers.p15.tools.studio_start_work.approval_mode="approve"',
                "-c",
                'mcp_servers.p15.tools.studio_handoff.approval_mode="approve"',
                "-c",
                'mcp_servers.p15.tools.studio_sync.approval_mode="approve"',
            ]
        if label == "directed":
            command[-1:-1] = [
                "-c",
                "developer_instructions="
                + json.dumps((ROOT / ".agents/skills/studio-task/SKILL.md").read_text()),
            ]
    else:
        env.update(
            XDG_CONFIG_HOME=str(workspace / "xdg"),
            OPENCODE_TEST_HOME=str(workspace),
            OPENCODE_TEST_MANAGED_CONFIG_DIR=str(workspace / "managed"),
            OPENCODE_CONFIG_DIR=str(workspace / ".opencode"),
            OPENCODE_DISABLE_PROJECT_CONFIG="true",
            OPENCODE_DISABLE_EXTERNAL_SKILLS="true",
            OPENCODE_DISABLE_CLAUDE_CODE="true",
            OPENCODE_DISABLE_DEFAULT_PLUGINS="true",
        )
        read_rules = {"*": "deny", ".": "allow"}
        for file in workspace.rglob("*"):
            for value in (
                str(file),
                file.as_posix(),
                str(file.relative_to(workspace)),
                file.relative_to(workspace).as_posix(),
            ):
                read_rules[value] = "allow"
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    "p15": {"type": "local", "command": [str(PYTHON), "-m", "studio_mcp.server"]}
                },
                "permission": {
                    "*": "deny",
                    "read": read_rules,
                    "external_directory": "deny",
                    "skill": "allow",
                    "p15_*": "allow",
                },
                "agent": {"build": {"steps": 12}},
            }
        )
        resolved = shutil.which("opencode.cmd")
        if not resolved:
            raise RuntimeError("opencode.cmd missing")
        prefix = ["cmd.exe", "/d", "/c", resolved]
        diagnostic = subprocess.run(
            prefix + ["debug", "config", "--pure"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
        )
        try:
            config = json.loads(diagnostic.stdout)
        except json.JSONDecodeError:
            save(
                "opencode-isolation.json",
                {
                    "exit_code": diagnostic.returncode,
                    "parseable": False,
                    "stderr": diagnostic.stderr[-1200:],
                },
            )
            return
        safe = {
            "exit_code": diagnostic.returncode,
            "mcp_names": list(config.get("mcp", {})),
            "plugin_count": len(config.get("plugin", [])),
            "permission": config.get("permission"),
            "agents": list(config.get("agent", {})),
        }
        save("opencode-isolation.json", safe)
        assert safe["mcp_names"] == ["p15"] and not safe["plugin_count"], safe
        assert (
            safe["permission"]["*"] == "deny" and safe["permission"]["external_directory"] == "deny"
        )
        command = prefix + ["run", "--pure", "--format", "json", prompt]
    save(
        f"launch-{run_id}.json",
        {
            "harness": harness,
            "scenario": scenario,
            "variant": label or "spontaneous",
            "workspace": str(workspace),
            "prompt": prompt,
            "command": command,
            "timeout_seconds": 150,
        },
    )
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    timeout = False
    try:
        stdout, stderr = process.communicate(timeout=150)
    except subprocess.TimeoutExpired:
        timeout = True
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        stdout, stderr = process.communicate(timeout=15)
    # Native init metadata can contain private instruction text; omit it from retained JSONL.
    retained = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "system":
            event = {
                k: event[k]
                for k in (
                    "type",
                    "subtype",
                    "model",
                    "tools",
                    "mcp_servers",
                    "skills",
                    "agents",
                    "session_id",
                )
                if k in event
            }
        if event.get("type") == "tool_use" and event.get("part", {}).get("tool") == "read":
            state = event["part"]["state"]
            path = state.get("input", {}).get("filePath", "")
            if not Path(path).is_relative_to(workspace):
                state["output"] = "[OMITTED: outside fixture]"
        retained.append(event)
    (TRACE / f"{run_id}.jsonl").write_text(
        redact("\n".join(json.dumps(e, ensure_ascii=False) for e in retained)), encoding="utf-8"
    )
    (TRACE / f"{run_id}.stderr.log").write_text(redact(stderr[-5000:]), encoding="utf-8")
    save(
        f"run-{run_id}.json",
        {
            "exit_code": process.returncode,
            "seconds": time.monotonic() - started,
            "timeout": timeout,
            "event_count": len(retained),
        },
    )
    print(harness, scenario, process.returncode, "events", len(retained), "timeout", timeout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("harness", choices=["claude", "codex", "opencode"])
    parser.add_argument("scenario", choices=["readonly", "tracked", "failed", "provided"])
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    run(args.harness, args.scenario, args.label)
