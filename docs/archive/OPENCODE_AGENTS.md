# OpenCode development agents (internal tooling)

> These four agents remain repository development tooling and are not part of
> the Studi'OS public/runtime architecture: not API, not MCP tools, not server
> permissions, not user profiles, not protocol. They assist whoever develops
> this repository under OpenCode, mirroring the Codex harness roles.

| Agent | Version Codex (baseline) | Version OpenCode |
|---|---|---|
| `studio-architect` | `.codex/agents/studio-architect.toml` | `.opencode/agents/studio-architect.md` |
| `studio-tester` | `.codex/agents/studio-tester.toml` | `.opencode/agents/studio-tester.md` |
| `contract-guardian` | `.codex/agents/contract-guardian.toml` | `.opencode/agents/contract-guardian.md` |
| `sync-debugger` | `.codex/agents/sync-debugger.toml` | `.opencode/agents/sync-debugger.md` |

Baseline behavior is preserved as-is; the `.codex/` files stay the reference.
A light duplication between the two directories is accepted and documented
here instead of a shared generator (no generic framework, per task scope).

## Invocation

Subagents invocables par `@mention` ou auto-dispatch via `description` :

```
@studio-architect <tâche d'analyse architecture>
@studio-tester <paquet à valider : but, diff, critères>
@contract-guardian <changement à relire>
@sync-debugger <symptôme sync/offline/transfert>
```

`opencode run --agent <nom>` ne fonctionne PAS pour ces agents : OpenCode
1.18.31 refuse d'exécuter un `subagent` en tête (`Falling back to default
agent`). Passer par une session primaire qui délègue (`@mention`).

## Modèles (config de dev, une ligne `model:` par fichier, modifiable librement)

Auth locale disponible au portage : provider `opencode-go` (+ modèles gratuits
`opencode/*-free` sans moyen de paiement).

| Agent | Codex (non utilisable sous OpenCode) | OpenCode 1.18.31 |
|---|---|---|
| `studio-architect` | `gpt-6-astra` (reasoning high) | `opencode-go/kimi-k3` |
| `studio-tester` | `gpt-5.6-terra` (medium) | `opencode-go/kimi-k2.7-code` |
| `contract-guardian` | `gpt-5.6-terra` (medium) | `opencode-go/kimi-k2.7-code` |
| `sync-debugger` | `gpt-5.6-terra` (medium) | `opencode-go/kimi-k2.7-code` |

`model_reasoning_effort` Codex n'a pas d'équivalent confirmé en 1.18.31
(`reasoningEffort` n'existe que dans la doc récente, sans support vérifié par
le binaire local) : non repris. Les tests live ont été exécutés avec
`opencode/muse-spark-1.3-contributor-free` (override temporaire, reverté).

## Permissions techniques (frontmatter, vérifiées via `opencode debug agent`)

| Agent | `edit` | `bash` |
|---|---|---|
| `studio-architect` | `deny` | deny sauf `*graphify-studio*`, `git status/log/diff*` |
| `sync-debugger` | `deny` | idem architect |
| `contract-guardian` | `ask` (report-only par défaut, fix explicite possible avec approbation) | idem architect |
| `studio-tester` | `deny` | `allow` (pytest/ruff/mypy requis) |

Écarts connus assumés : `bash: allow` du tester ne peut pas être restreint
techniquement aux seules commandes de test en 1.18.31 — la règle
no-modification repose aussi sur l'instruction (rappelée dans le prompt).
Graphify : l'agent ne peut plus rafraîchir le graphe lui-même hors launcher
autorisé ; s'il faut un refresh, il rend la commande exacte à l'orchestrateur
(la baseline Codex supposait un shell complet).
Règle Windows du tester : la distinction PowerShell-vs-Bash du harness Claude
ne s'applique pas sous OpenCode (outil `bash` unique) — consigne réduite à
l'essentiel (commandes minimales, non-destructives, pas de test inventé).

## Validation effectuée (OpenCode 1.18.31)

- `opencode agent list` : 4 agents découverts en `subagent`, permissions résolues conformes.
- `opencode debug agent <nom>` : model/prompt/description/tools résolus conformes (`edit: false` là où `deny`).
- `@mention` + délégation : 4/4 OK (orchestrateur `build` sur modèle gratuit).
  - architect : listing TECH correct (10 fichiers), tentative de création `probe-architect.txt` refusée par l'agent, `Test-Path` = False.
  - tester : Tier 1 justifié, `git status --short` exécuté, rien modifié.
  - guardian : `Verdict: Compliant` auto-référé, format de sortie conforme.
  - sync-debugger : split Client SQLite / Serveur Postgres restitué.
- Non testé avec les modèles `opencode-go/*` cibles (moyen de paiement requis
  sur le workspace) : à rejouer après activation billing si besoin.
