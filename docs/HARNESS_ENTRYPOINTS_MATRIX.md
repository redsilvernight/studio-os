# Démarrage et reprise cohérents entre harnais

Étape roadmap `entrypoints` (roadmap « Adaptation produit pour les futures
bibliothèques IA », tâche `e5bd13c9`). Ce document est la matrice de ce qui est
supporté au démarrage d'une session, avec la preuve associée.

## Ce que fait un démarrage de session

1. Le plugin/hook du harnais reçoit le répertoire courant (`cwd`) et, quand le
   harnais l'expose, le modèle observé (`model`).
2. Hors projet suivi, il ne rend rien (code 0, sortie vide).
3. Projet suivi : il rend le `project_id` du workspace et l'`agent_id` à passer
   à `studio_start_work` / `studio_log_ai_work`.
4. L'`agent_id` vient de `studio-client agents ensure`, authentifié avec **le
   credential du harnais lui-même** (`--harness-credential`), puis mis en cache
   dans `~/.claude/studio-agent.json`, clé = origine serveur + empreinte du
   fichier de configuration de l'outil.

## Matrice

| Point d'entrée | Fichier d'intégration | Sortie | Identité agent | Création d'agent |
|---|---|---|---|---|
| Claude Code (CLI/Desktop) | `~/.claude/scripts/studio-session-start.ps1`, enregistré dans `~/.claude/settings.json` (`hooks.SessionStart`) | enveloppe JSON `hookSpecificOutput.additionalContext` | `~/.claude.json` → `mcpServers.studio-os` | aucune si le cache est valide ; sinon `ensure` par clé stable |
| OpenCode CLI/Desktop | plugin managé `~/.config/opencode/plugins/studio-os.js` → `~/.config/opencode/scripts/studio-session-start-opencode.ps1` | texte injecté dans `system` (`ctx.session.hook("context")`) | `~/.config/opencode/opencode.json[c]` → `mcp.studio-os` (JSONC, commentaires et virgules finales tolérés) | idem |
| Codex CLI | `~/.codex/studio-session-start-codex.ps1`, enregistré dans `~/.codex/hooks.json` (`hooks.SessionStart`) | texte | `~/.codex/config.toml` → `[mcp_servers.studio-os.http_headers]` | idem |
| Lancement Studio OS (Desktop → harnais) | même hook/plugin, dans l'environnement du lancement | idem | credential éphémère du lancement (`STUDIO_CLIENT_MACHINE_TOKEN`), prioritaire sur l'adoption | idem, sur la machine du lancement |

Le credential adopté est celui du **couple (poste, outil)** (DEC-0104 §2 /
DEC-0226) : chaque outil a sa propre machine Studi'OS. Un harnais câblé sur une
autre origine serveur que le workspace n'est jamais adopté (aucun jeton deviné,
aucun repli silencieux sur un autre jeton) ; le hook retombe alors sur
l'identité locale du poste, comme avant.

## Changement de modèle

- Le harnais qui expose le modèle (OpenCode, Claude Code via `payload.model`)
  appelle `agents ensure --model-identity` : une fiche par (poste, provider,
  modèle), partagée entre harnais (DEC-0225), clé de cache
  `agent-model-v2:<origine>:<harness>:<modèle>`.
- Modèle inconnu ou endpoint absent : repli explicite sur l'agent du harnais,
  ligne « ce modèle sur ce poste » absente — jamais un agent inventé.

## Preuves

| Critère | Preuve |
|---|---|
| Adoption du credential de l'outil | `tests/client/test_session_credential.py` (14 cas : 3 harnais, origine étrangère, config absente/illisible, Bearer absent) |
| Le hook passe `--harness-credential` et ne lit plus de jeton | `tests/client/test_setup_hooks.py::test_every_hook_adopts_the_harness_own_credential`, `::test_opencode_hook_asks_ensure_for_the_harness_credential` (exécution PowerShell réelle, cache clé par empreinte) |
| L'agent rendu appartient à la machine du MCP | `tests/client/test_agents_ensure.py::test_cli_agents_ensure_adopts_the_harness_credential` (le `Authorization` réellement envoyé est celui de l'outil) |
| Un jeton explicite gagne toujours | `tests/client/test_agents_ensure.py::test_cli_agents_ensure_keeps_an_explicit_token` |
| Projections sans dérive | `studio-client adapters check` → `checked 26, failures 0` |
| Types | `mypy` sur les 6 paquets/services → 382 fichiers, 0 erreur |

Constat en direct (27/10/2026), sur ce poste : avant correctif,
`agents ensure --harness opencode` rendait un agent de la machine `269dc2bf…`
(machine du poste) alors que le MCP OpenCode s'authentifie comme `4d0e6441…`
(machine de l'outil) ; `studio_start_work` répondait `actor_not_owned`. Avec
`--harness-credential`, l'agent rendu appartient bien à `4d0e6441…`.

## Limites connues

- Le serveur de production ne sert pas encore `POST /api/v1/agents/resolve-identity`
  (404 avec credential valide, alors que `/agents` et `/agents/ensure` répondent).
  La fiche par modèle reste donc côté dev tant que la release n'est pas déployée ;
  le hook se replie proprement sur l'agent du harnais.
- Les hooks déjà déployés sur un poste ne changent qu'après
  `studio-client setup-hooks` (fichier managé inchangé = non réécrit sans
  `--overwrite`). Un poste qui garde l'ancien hook continue de créer un agent par
  conversation : c'est un état de poste, pas une divergence du dépôt.
- Lancement Codex : l'adaptateur ne substitue pas de credential éphémère (il
  laisse l'entrée de l'utilisateur) ; le hook adopte donc le credential durable
  de l'outil, cohérent avec le MCP que Codex utilise réellement.
