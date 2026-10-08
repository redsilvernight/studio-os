---
id: DEC-0176
title: 'AIB R3 : lancement non interactif des harness (permissions bornees, timeout
  dur)'
status: accepted
date: '2026-10-01'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0176 — AIB R3 : lancement non interactif des harness (permissions bornees, timeout dur)

Roadmap AIB, etape R3 (tache `50ef918a`). Statut `accepted` (accord humain du 2026-10-01 ; fichier et serveur alignes).

## Decide

- L'invocation non interactive est **la responsabilite de l'adapte** : chaque
  `HarnessAdapter` declare `headless_argv(prompt)` ; l'executable est resolu par
  `resolve_executable` (entree PATH absolue hors workspace, jamais le depot). Un
  harness sans mode non interactif refuse (`headless_unsupported`).
- Invocations bornees retenues (2026) :
  - Claude Code : `claude -p <consigne> --output-format text --permission-mode
    acceptEdits --allowedTools "Read,Edit,Write,Bash,Grep,Glob"` ;
  - OpenCode : `opencode run --auto <consigne>` ;
  - Codex : `codex -a never exec --sandbox workspace-write <consigne>`.
- **Permissions bornees explicites**, pas de bypass total : le harness peut lire,
  editer et tester, mais l'autonomie reste minimale. Le garde-fou Git Studio OS
  (`studio-git-guard`) reste la barriere contre push/merge ; aucun push ni merge
  automatique.
- **Identite (L1)** : on s'appuie sur le hook/plugin deja installe (resout
  `project_id`, `slug`, `agent_id` depuis le chemin de worktree `<repo>-wt-<id8>`).
  La consigne ne transporte que des ids et une cle stable, jamais de secret ni de
  ligne de shell. Limite connue : le hook Codex est encore manquant (L1).
- **Timeout dur** : une execution depasse `launch_timeout_seconds` (defaut 3600 s)
  => arbre de processus tue (pas d'orphelin), resultat `timed_out`, `exit_code`
  nul. Sortie captee bornee (`MAX_OUTPUT_BYTES`), expurgee par l'executeur.
- L'execution est **bloquante, hors boucle asyncio** (`asyncio.to_thread`) ; le
  handle de processus permet l'annulation.

## Consequences

- Ajoute `HarnessAdapter.headless_argv` / `resolve_executable`, le module
  `studio_client.daemon.launch_runner`, le reglage `launch_timeout_seconds`, et
  leurs tests. Contrat `TaskLaunch` inchange.
- Reste a l'etape R3 (tache `0c5ace15`) : rapports d'etat via l'outbox,
  expurgation des journaux, annulation via l'API, cablage dans la boucle heartbeat.
- Ecarte : `--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox`
  (permissions trop larges) ; lancement d'un shim `.cmd`/`.bat` (re-analyse
  d'arguments, injectable) ; prompt passe par stdin (idiome non uniforme selon
  les harness).
