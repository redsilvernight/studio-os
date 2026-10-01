# AIB R5 — Démonstration réelle : Dashboard → machine → session → handoff

Statut : démonstration exécutée le 2026-10-01 sur une stack **locale réelle** (API courante
`dev`, PostgreSQL, daemon depuis les sources, harness `opencode` réel). Le VPS de production
n'a **pas** été utilisé (voir §5).

Tâche : `a49f3803-b6c9-4cd4-b442-589e5aa2f26e` — « [AIB R5] Démonstration réelle documentée ».
Étape de roadmap : `Project AI Bootstrap`, phase `remote-launch`, étape **R5**.

## 1. Objet

Démontrer de bout en bout la chaîne de lancement à distance, sur un vrai projet et un vrai
harness, et pas seulement avec le harness factice du test CI :

`Dashboard (demande) → machine cible (tirage, politique locale, worktree) → harness réel
(opencode) → studio_start_work → travail → studio_handoff → événements serveur`.

Ce que la démonstration doit prouver :
- la boucle complète produit une **session** et un **handoff** réels (pas seulement un exit 0) ;
- les **gates** serveur et machine fonctionnent (opt-in, liste de harnais autorisés) ;
- le rapport de capacités (R1) est bien remonté par la machine.

## 2. Méthode et fenêtre

Environnement monté localement, code courant de `dev` (merge `24e1779`) :

| Brique | Comment |
|---|---|
| Base | PostgreSQL local (`studio-os-test-pg`), base dédiée `studio_r5_demo`, `alembic upgrade head` (0026) |
| API | `services/api` depuis les sources (`uvicorn studio_api.main:app`, 127.0.0.1:8000) |
| MCP | `python -m studio_mcp.server` en **stdio**, déclaré dans la config du dépôt de démo |
| Machine cible | `studio-client-daemon` depuis les sources (venv éditable), machine `r5-target` |
| Projet de démo | dépôt Git neuf `r5-demo-repo` (origine locale, branche `dev`), projet serveur `r5-demo` |
| Harness | `opencode.exe` 1.18.32 réel, modèle `opencode-go/deepseek-v4.1-flash` |

Fenêtre : 2026-10-01, 19:36–20:25 UTC. Machine cible : `e4ecb1b0-b7c5-44ac-9501-030d6245bc59`.

Le daemon est lancé côté machine B avec `--agent-id` (agent `studio-opencode` de la machine),
opt-in de lancement et liste de harnais autorisés ; le projet de démo est déclaré via
`git_watches`. La demande est créée via l'API (`POST /api/v1/projects/{id}/task-launches`),
c'est-à-dire exactement ce que fait le panneau « Lancer sur… » du Dashboard (R4).

## 3. Résultats mesurés

| # | Scénario | Verdict | Preuve |
|---|---|---|---|
| 1 | Boucle complète pilotée par le daemon (harness réel) | **succeeded** | lancement `4bc486d2…`, session `10cab95c…`, tâche `completed`, `HELLO_R5.md` |
| 2 | Machine non opt-in → création refusée côté serveur | **refusée** | HTTP `{"error_code":"machine_not_opted_in"}` |
| 3 | Harnais non autorisé localement → refus machine | **rejected / harness_not_allowed** | lancement `3035cd22…` |
| 4 | Rapport de capacités (R1) remonté | **OK** | `machines.capabilities` (harness + versions + projet + opt-in) |
| 5 | Coupure réseau, annulation, rejeu | couverts par le CI | `tests/client/test_launch_e2e_acceptance.py` (harness factice) |

Séquence réussie (scénario 1, extrait `events`) :

```
20:15:49 task_launch.requested  requested
20:16:01 task_launch.accepted   accepted
20:19:23 task.started           in_progress
20:19:23 session.started
20:20:13 task.completed         completed
20:20:14 ai_work.started/completed (changed_files=[HELLO_R5.md])
20:20:15 session.ended
20:21:06 task_launch.finished   succeeded   (reason_code=none)
```

- Lancement : `status=succeeded`, `reason_code=none`, `version=5`.
- Session : `10cab95c-233e-468c-984c-f8d01e50b427`, machine `e4ecb1b0…`, agent `8725af64…`.
- Travail : `HELLO_R5.md` créé dans le worktree `r5-demo-repo-wt-327304ba` (une ligne `Demo R5 OK`),
  `git status` : seul ce fichier non suivi ; **rien poussé**.
- Ledger : `ai_work 1677df8e…`, `changed_files=['HELLO_R5.md']`.

## 4. Constats

1. **La boucle complète fonctionne** de bout en bout avec un harness réel : le daemon tire la
   demande, applique la politique locale, crée le worktree (`git worktree add`, branche
   `task/<id8>-<slug>` sur `origin/dev`), lance `opencode`, et l'agent appelle `studio_start_work`
   puis `studio_handoff`.
2. **Deux niveaux de garde se complètent** : le serveur refuse la *création* pour une machine
   non opt-in (`machine_not_opted_in`), et la machine refuse *localement* un harnais absent de sa
   liste (`harness_not_allowed`). Aucune commande libre n'est représentable.
3. **Le modèle du harness doit être imposé** : sans forçage, `opencode run` retombe sur un modèle
   par défaut (`gpt-5.6-luna`) qui **n'exécute pas** la consigne `studio_start_work`/`studio_handoff`
   (lancement « succeeded » mais session nulle, tâche intacte). Il faut fixer le modèle
   (`agent.build.model` / config dédiée via `OPENCODE_CONFIG`).
5. **Le launcher Windows `.cmd` est refusé** (protection contre l'injection shell) : le daemon doit
   résoudre le vrai `opencode.exe`, pas le shim npm `opencode.cmd`.

## 5. Limites de la mesure

- **La production n'expose pas la fonctionnalité.** Le serveur `flo-laptop` répond sans le
  schéma `MachineCapabilities` et **sans aucun endpoint `task-launches`** (`/openapi.json`) : la
  chaîne R1–R4 est sur `dev`, pas encore promue vers `master`/déployée. La démo a donc été faite
  sur une stack locale au code courant. Un heartbeat avec capacités y renvoie `422 extra_forbidden`.
- **Pas de MinIO** : le flux de lancement n'échange aucun octet de fichier ; seuls PostgreSQL et
  l'API sont nécessaires. Les transferts restent hors périmètre.
- **Coupure réseau / annulation / rejeu** ne sont pas rejoués ici avec le harness réel ; ils sont
  couverts par le test E2E CI (harness factice). Une annulation réelle d'un harness LLM en cours
  n'a pas été chronométrée.
- **Bruit MCP** : le harness lancé hérite de serveurs MCP globaux de la machine (obsidian-memory,
  etc.) dont les schémas génèrent de nombreux avertissements `unknown format "uint"`. Sans impact
  sur le succès, mais la sortie capturée en est saturée.
- **Pas de lien lancement ↔ session** : `TaskLaunch.session_id` reste `null` après succès. La
  session existe et le handoff est tracé, mais le lancement n'est pas rattaché à sa session ; le
  Dashboard ne peut donc pas « ouvrir la session résultante » depuis l'enregistrement du lancement.
- **Un seul poste** : la démo simule deux « machines » (demandeur = propriétaire, cible = même
  poste). Le scénario deux postes réels (A demande, B exécute) reste à faire.

## 6. Décisions / écarts proposés

- **Défaut à corriger** : faire remonter `session_id` sur le `TaskLaunch` (le daemon connaît le
  lancement et observe la session du harness) — sinon la promesse « ouvrir la session » de R4 est
  incomplète.
- **Robustesse harness** : documenter/adapter `headless_argv` pour imposer un modèle exploitable
  et isoler la config MCP du harness (éviter l'héritage des MCP globaux de l'opérateur).
- **Déploiement** : promouvoir la phase `remote-launch` (dev → master) et redéployer le VPS avant
  toute démonstration en production.

## 7. Critères de réexamen

- Rejouer la démonstration **après déploiement** de la phase sur le VPS, avec deux postes réels.
- Rejouer dès que `TaskLaunch.session_id` est relié à la session du harness.
- Ajouter au CI un test qui lance le **vrai** `opencode` en mode headless (aujourd'hui factice).

## 8. Preuves

- Création de la demande (scénario 1) :
  `POST /api/v1/projects/5d207aa6-…/task-launches` → `201`, `id=4bc486d2-6d9d-4e99-a022-5e2085b000a0`.
- État final du lancement :
  `GET /api/v1/task-launches/4bc486d2-…` → `status=succeeded`, `reason_code=none`, `version=5`.
- Session : `studio-client sessions list` → `10cab95c-…` (started 20:19:23, ended 20:20:14).
- Ledger : `studio-client ai-work list` → `1677df8e-…`, `changed_files=['HELLO_R5.md']`.
- Fichier produit : `r5-demo-repo-wt-327304ba/HELLO_R5.md` → `Demo R5 OK` ; `git status` : `?? HELLO_R5.md`.
- Capacités R1 : `machines.capabilities` →
  `{"harnesses":[{"harness_id":"claude-code","detected":true,"version":"2.1.272"},
  {"harness_id":"codex","detected":false},{"harness_id":"opencode","detected":true,"version":"1.18.32"}],
  "project_ids":["5d207aa6-…"],"accepts_launches":true,"max_launches":1}`.
- Refus serveur : `POST …/task-launches` (machine opt-in off) → `{"error_code":"machine_not_opted_in"}`.
- Refus local : lancement `3035cd22-…` → `status=rejected`, `reason_code=harness_not_allowed`.
- Production : `GET https://flo-laptop.tailf61f85.ts.net/openapi.json` → aucun chemin `task-launches`,
  pas de `MachineCapabilities` ; heartbeat avec capacités → `422 extra_forbidden`.
