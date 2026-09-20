# Roadmaps — findings post-convergence P6/P8 (2026-09-20)

Constats hors périmètre du chantier Roadmaps, relevés pendant la convergence
P6 + P8. Aucun n'est corrigé ici. Source de vérité des décisions :
`docs/DECISIONS.md` ; ce fichier ne consigne que des points à traiter.

| # | Finding | Constat | Suite proposée |
|---|---|---|---|
| 1 | Enregistrement d'agent (MCP) | `POST /api/v1/agents` est HTTP-only ; `studio_log_ai_work` exige un `agent_id` (tâche W2). | Enregistrement/retrouvaille automatique au démarrage de session. |
| 2 | Identité machine courante | Aucun outil MCP ne dit « quelle machine suis-je » ; `GET /machines` liste toutes les machines. | Exposer l'identité de la machine authentifiée. |
| 3 | Heartbeat en écriture (MCP) | Le heartbeat n'est écrit que par le daemon (`POST /api/v1/heartbeats`) ; aucune surface MCP. | Décider si une session non-daemon doit pouvoir le signaler. |
| 4 | Handoff | Aucune surface : clôture = ≈9 appels (statut, claims un à un, `log_ai_work`, fin de session, tâche restée claimée). | Tâche W1 `studio_handoff` ; `end_session` devrait libérer les claims de la tâche. |
| 5 | Numérotation des DEC | `Decision.readable_id` (serveur) n'est pas synchronisé avec `docs/decisions/DEC-xxxx` : P6 a reçu `DEC-0086`, P8 `DEC-0087`, deux numéros déjà pris dans le dépôt ; P6 et P8 ont chacune créé une fiche `DEC-0088` (P8 renumérotée `DEC-0089`). | Décision d'architecture : un seul compteur, ou identifiant serveur distinct du numéro ADR. |
| 6 | Ergonomie AI work | Vocabulaire de statut non découvrable (`in_progress` refusé ; valeurs : `started`, `completed`, `failed`, `review_requested`, `approved`, `changes_requested`). | Message d'erreur listant les valeurs valides / doc de l'outil. |
| 7 | Retard de déploiement VPS | Le serveur déployé n'expose pas encore les routes `/roadmaps` (404) ni la section Roadmap de `studio_prepare_context` ; le code intégré n'y est pas déployé. | Déploiement avant le E2E de P10. |
| 8 | Bootstrap workspace/tests | `ruff`/`pytest` ne sont pas sur le PATH ; seul `.venv\Scripts\python.exe -m …` fonctionne ; Postgres de test sur `localhost:5432` (`studio_os_test`), MinIO `:9000`. | Script de bootstrap/validation (voir W6). |
| 9 | Synchronisation Vault | `projects/studio-os/CURRENT.md` (AI-Memory) était resté à P1. La convergence y a préfixé l'état Roadmaps (P0→P9, prochaine action P10) et corrigé `summary_50` ; les anciennes sections « Prochaine action » (P0/P1, titres en double) restent à purger. | Nettoyage complet à la clôture de P10 (le vault est hors dépôt). |
| 10 | Project Initialization Unit-of-Work | `apply_initialization` n'est pas atomique : cinq services commitent eux-mêmes — `projects.create_project`, `roadmaps.import_roadmap` (via `finish_result`, qui commit puis diffuse les événements temps réel), `link_task_by_step_key`, `library.set_lock`, `runtime_bindings.create_binding` ; seules les Tasks ont une variante sans commit (`add_task`). Reste rejouable (idempotent). | Chantier séparé : variantes sans commit + diffusion après un commit unique (voir DEC-0088 §6). Non bloquant sauf preuve par P10. |
| 11 | Artefacts E2E | `output/` et le dossier `3479c52/` (worktree Git imbriqué) restent non suivis à la racine ; `3479c52/` pollue Graphify (F4 de DEC-0084). | Les sortir du dépôt / les ignorer. |
| 12 | État des Tasks | Les Tasks P2–P5, P7 et P9 étaient restées `created`/`in_progress` alors que leur code est intégré ; une session P7 restait ouverte. | Aligné pendant cette convergence ; à faire à chaque clôture de lane. |
| 13 | E2E « 5 onglets » | L'onglet Roadmap (P7) porte le workspace projet à 6 onglets ; 4 tests Playwright UI-4/14/15 assertaient encore 5 (échecs déjà présents sur le master issu du merge P7/P9) : attentes mises à jour à 6 dans la convergence. | Ajouter l'onglet suivant = mettre à jour ces trois specs. |

