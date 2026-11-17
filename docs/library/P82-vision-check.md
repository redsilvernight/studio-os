# P82 — Vérification de la vision Library

Audit seul : aucun code produit n'a été modifié. Chaque énoncé de la vision est
confronté au code qui l'implémente, au test qui le prouve, et à la commande
exacte lancée avec son résultat réel. Une commande non lancée est marquée
« non exécuté » ; aucun résultat n'est extrapolé.

## Environnement d'exécution

- Worktree : `C:\Users\redsi\AppData\Local\opencode-dispatch\worktrees\studi'os\6c5b9d28-audit-aucun-code-produit-mod`
  (commit `871f1e7a`), venv du worktree (`.venv/Scripts/python.exe`, Python 3.14.7).
- Les commandes pytest sont lancées avec `.venv/Scripts/python.exe -m pytest …`
  depuis la racine du worktree. L'interpréteur du `.venv` principal cité dans
  la consigne est hors worktree et inaccessible depuis cette session ; le même
  argumentaire pytest, lancé avec le venv du worktree, passe :
  **1303 passed, 2 skipped, 1 xfailed in 276.79s** (EXIT 0).
- Piste du brief : le module `library_equivalence` n'existe pas sous ce nom
  dans ce worktree (`grep` sur tout le dépôt : 0 occurrence dans le code, seules
  mentions = ce document). L'équivalence est portée par
  `adapters_check.check_adapters` et `drift.classify_state`.

## Tableau « énoncé → preuve »

| # | Énoncé | Implémentation (fichiers / fonctions) | Preuve (test + commande → résultat) | Verdict | Écart |
|---|---|---|---|---|---|
| 1 | Library = source canonique unique de la config IA (studio, project, user) | `services/api/src/studio_api/services/library.py` (`create_resource`, `create_resource_version`, `activate_resource_version`, `_read_clause`), `services/api/src/studio_api/routers/library.py`, `packages/studio-contracts/src/studio_contracts/library.py` (`LibraryScope`), `packages/studio-client/src/studio_client/projection_source.py` (`fetch_projection_bundle` : tout est lu par HTTP), `packages/studio-client/src/studio_client/canonical.py` (rendu pur depuis le bundle) | `test_daemon_library_sync.py::test_fetch_only_reads_the_library_never_publishes` (le client ne fait que `list_library_resources` + `batch_library_versions`) et `test_p80_library_canonical_e2e.py` (publication → activation → projection locale). `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/client/test_daemon_library_sync.py` → « 9 passed in 2.38s » ; `… tests/client/test_p80_library_canonical_e2e.py` → « 1 passed in 8.20s » | prouvé | Aucun code ne lit `.agents/` comme source (P45) ; la piste `library_equivalence` du brief est absente (voir plus haut) |
| 2 | Projections locales dérivées (aucune dérive) | `packages/studio-client/src/studio_client/adapters_check.py` (`check_adapters` : compare chaque artefact à une projection fraîche du bundle), `…/drift.py` (`classify_state` : `current` / `missing` / `outdated` / `locally_modified`), `…/projection_source.py` (`bundle_from_resolved`), `…/skill_sync.py` (`plan_skill_sync`), `…/canonical.py` | `tests/protocol/test_p40_projection_source.py::test_adapters_check_passes_on_repo_without_agents_dir` et `::test_adapters_check_reports_drift_without_agents_dir` ; `tests/harness/test_drift_taxonomy.py::test_classify_state_covers_four_states` ; adaptateurs. `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/protocol/test_p40_projection_source.py tests/harness/test_drift_taxonomy.py` → « 20 passed in 3.38s » ; `… tests/client/adapters/test_adapters_p10.py` → « 56 passed in 1.14s » | prouvé | Le gate `studio-client adapters check --project-id <id>` (projections réelles du dépôt vs Library) n'est pas lancé en CI ; seuls les tests unitaires du gate le sont |
| 3 | Synchro automatique dès l'activation d'une version (événement `library.*` → daemon) | `packages/studio-client/src/studio_client/daemon/library_events.py` (`LibraryEventWatcher`, `LIBRARY_TRIGGER_TYPES`), `…/daemon/runtime.py` (instanciation avec `on_library_change=self._mark_library_updates_pending`), `…/daemon/skills_bridge.py` (`mark_update_pending`, `start_auto_sync`, `_AutoSyncRunner`), `services/api/src/studio_api/services/library.py` (`_emit_library_event`, `activate_resource_version`) | `test_daemon_library_events.py` (activation déclenche une fois, pas de rejeu, reprise après coupure, curseur persistant) ; `test_library.py::test_studio_scope_activation_emits_to_every_active_project`. `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/client/test_daemon_library_events.py` → « 6 passed in 1.72s » ; `… tests/api/test_library.py` → « 25 passed in 3.70s » | partiel | L'événement ne fait que marquer `update_pending` (`mark_update_pending`) ; l'application automatique est faite par `_AutoSyncRunner` (thread one-shot lancé au démarrage du daemon et à l'activation du réglage auto-sync via `configure_skills`). Un daemon déjà lancé n'applique pas la nouvelle version à la réception : il attend un redémarrage, une réactivation du réglage, ou une confirmation UI |
| 4 | Application après confirmation dans l'UI | `dashboard/src/skillsSync.ts` (choix par élément, « Appliquer N choix », confirmation, envoi `skills.apply` avec `confirm: true` et `preview_hash`), `dashboard/src/skillsApi.ts`, `packages/studio-client/src/studio_client/daemon/skills_bridge.py` (`preview_skills`, `apply_skills` : refus sans `confirm` ou avec aperçu périmé) | `dashboard/src/skillsSync.test.ts` (« applies only explicit per-skill choices after reviewing the replacements », « keeps local choices without authorizing a global overwrite ») ; `test_daemon_skills_bridge.py` (aperçu périmé/choix inconnu n'écrit rien, rejeu idempotent) ; P80 (apply sans confirmation → `LocalFeatureError`, puis `confirm=True` + `preview_hash` écrit). `npx vitest run src/skillsSync.test.ts src/views/libraryMerge.test.ts src/views/library.test.ts` → « 97 passed (dont skillsSync 20) » ; `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/client/test_daemon_skills_bridge.py` → « 31 passed in 3.29s » ; P80 → « 1 passed in 8.20s » | prouvé | — |
| 5 | Tous les utilisateurs reçoivent le commun (scope studio) | `services/api/src/studio_api/services/library.py` (`_emit_library_event` : un événement par projet actif pour un scope `studio` ; `_read_clause` / `_can_read` : le scope `studio` est lisible par tout membre d'au moins un projet), `packages/studio-client/src/studio_client/projection_source.py` (`bundle_from_resolved` ne retire que les ressources `user`) | `test_library.py::test_studio_scope_activation_emits_to_every_active_project` (deux projets reçoivent le même événement) ; P80 (Alice et Bob projettent « Commun v1 » puis « Commun v2/v3 »). `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/api/test_library.py` → « 25 passed in 3.70s » ; P80 → « 1 passed in 8.20s » | prouvé | « Tous les utilisateurs » = membres d'au moins un projet (DEC-0103) : un compte sans membership ne voit pas le commun |
| 6 | Écarts locaux publiés en scope `user`, privés | `packages/studio-client/src/studio_client/daemon/skills_bridge.py` (`_publish_override` : crée/versionne une ressource `user` avec `derived_from`, puis l'active), `…/publish.py`, `dashboard/src/skillsSync.ts` (option « Publier comme mon override », envoyée comme choix `publish`), `services/api/src/studio_api/services/library.py` (`_can_read` : `user` = propriétaire ou admin ; 404 pour les autres) | `test_daemon_skills_bridge.py::test_publish_choice_creates_a_private_user_scope_version` (scope `USER`, `derived_from` le commun, pas de version sur le commun) ; `test_library.py::test_user_scope_isolated_without_existence_leak` et `::test_user_scope_writes_stay_owner_only` (404, aucun leak d'existence) ; P80 (Bob reçoit 404 et ne liste jamais l'override d'Alice). `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/client/test_daemon_skills_bridge.py` → « 31 passed in 3.29s » ; `… tests/api/test_library.py` → « 25 passed in 3.70s » ; P80 → « 1 passed in 8.20s » | prouvé | Privé vis-à-vis des autres utilisateurs ; l'admin peut lire une ressource `user` (DEC-0063), ce qui est documenté mais nuance « privés » |
| 7 | Écarts fusionnables avec les évolutions du commun | `packages/studio-contracts/src/studio_contracts/library_merge.py` (`merge_texts`, conflits structurés), `services/api/src/studio_api/services/library.py` (`preview_merge`, `apply_merge` : choix `merge` / `keep_override`, rien n'est écrit si un conflit reste), `dashboard/src/views/libraryMerge.ts` (trois volets, aperçu, résolution par bloc, publication) | `tests/api/test_library_merge_apply.py::test_clean_merge_combines_both_sides`, `::test_conflicting_merge_writes_nothing_until_resolved`, `::test_keep_override_rebases_without_touching_the_text` ; `tests/client/test_library_merge.py` (moteur trois voies) ; `dashboard/src/views/libraryMerge.test.ts` (résolution par bloc, publication bloquée tant qu'un conflit reste). `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/api/test_library_merge_apply.py tests/client/test_library_merge.py` → « 27 passed in 3.05s » ; `npx vitest run src/skillsSync.test.ts src/views/libraryMerge.test.ts src/views/library.test.ts` → « 97 passed (dont libraryMerge 21) » | prouvé | — |
| 8 | Retour au commun possible | `services/api/src/studio_api/services/library.py` (`apply_merge` : `REVERT_TO_COMMON` → `deprecate_resource`, historique conservé et réactivable), `packages/studio-client/src/studio_client/daemon/skills_bridge.py` (`revert_override`), `dashboard/src/views/libraryMerge.ts` (« Revenir au commun », confirmation), `dashboard/src/skillsSync.ts` | `test_library_merge_apply.py::test_revert_to_common_deprecates_and_is_restorable` (déprécié puis réactivé, texte d'origine intact) ; `libraryMerge.test.ts` (« Revenir au commun : confirme, applique, affiche l'erreur et rend la main ») ; P80 (retour au commun → « Commun v3 » reprojeté, restauration du backup possible). `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/api/test_library_merge_apply.py tests/client/test_library_merge.py` → « 27 passed in 3.05s » ; `npx vitest run src/skillsSync.test.ts src/views/libraryMerge.test.ts src/views/library.test.ts` → « 97 passed (dont libraryMerge 21) » ; P80 → « 1 passed in 8.20s » | prouvé | — |
| 9 | Code rendu mort par le changement supprimé | Processus : `docs/library/roadmap-pc/PC0-inventory.md` (inventaire et découpage PC1–PC4), commits `refactor(...): PC1/PC2/PC3 supprime le code mort` (voir `git log --oneline --all --grep="PC[0-9]"`), garde-fou `scripts/deadcode_check.py` + `tests/scripts/test_deadcode_check.py` | `tests/scripts/test_deadcode_check.py::test_guard_fails_on_planted_dead_function` (une fonction morte ajoutée fait échouer vulture) ; cas documenté : `studio_client/library_merge.py` réduit de 242 à 19 lignes après déplacement du moteur vers `studio_contracts` (PC0 annexe python-packages), et `bce95936` « shareValueHtml n'est plus exporté (knip) » (export rendu mort par le changement, retiré dans la même PR). `.venv/Scripts/python.exe -m pytest -q -o pythonpath=services/api/src tests/scripts/test_deadcode_check.py` → « 3 passed in 14.84s » | partiel | La suppression est vérifiée a posteriori par vulture/knip et en revue ; aucun mécanisme automatique ne prouve, changement par changement, que tout code rendu mort a été supprimé. Les angles morts du garde-fou (usage par les tests seulement, accès dynamiques) laissent passer des restes |
| 10 | Code mort de tout Studio OS supprimé (knip, vulture ou équivalent) | `scripts/deadcode_check.py` (point d'entrée unique), `scripts/deadcode_whitelist.py` (exceptions justifiées), `[tool.vulture]` de `pyproject.toml`, `dashboard/knip.jsonc`, `desktop/knip.jsonc`, job CI `deadcode` (`.github/workflows/ci.yml`, vulture 2.16 + knip 6.45.1) | `tests/scripts/test_deadcode_check.py` (le garde-fou passe sur le dépôt, passe sur une copie intacte, échoue sur une fonction morte plantée). `.venv/Scripts/python.exe -m scripts.deadcode_check` → « vulture : ok en 4.3 s ; knip dashboard : ok en 6.7 s ; knip desktop : ok en 4.3 s » ; `… pytest … tests/scripts/test_deadcode_check.py` → « 3 passed in 14.84s » | prouvé | Périmètre partiel : pas de CSS, ni `desktop/src-tauri` (Rust), ni le sidecar Python du desktop ; `tests/`, `scripts/`, `docs/`, `examples/`, `contracts/` hors analyse ; liste blanche par nom (un homonyme masque) ; « utilisé seulement par les tests » n'est pas détecté comme mort |

## Validation de la branche

Commande exécutée (argumentaire de la consigne, venv du worktree) :

```
.venv/Scripts/python.exe -m pytest -q -x -o pythonpath=services/api/src \
  packages/studio-client/src packages/studio-code-graph/src packages/studio-contracts/src \
  services/mcp/src packages/studio-workspaces/src tests/client tests/workspaces
```

Résultat : **1303 passed, 2 skipped, 1 xfailed in 276.79s** (EXIT 0),
en une seule exécution, sans flaky.

Complément dashboard (hors argumentaire Python) :

```
cd dashboard && npx vitest run src/skillsSync.test.ts src/views/libraryMerge.test.ts src/views/library.test.ts
```

Résultat : **97 passed (3 fichiers)** — `skillsSync` 20, `libraryMerge` 21,
`library` 56.

## Écarts restants

1. **Énoncé 3 — application non immédiate.** L'événement `library.version.activated`
   / `library.resource.deprecated` réveille le daemon (`LibraryEventWatcher`),
   mais celui-ci se contente d'écrire `update_pending`
   (`mark_update_pending`). L'application automatique est faite par
   `_AutoSyncRunner` (thread one-shot lancé au démarrage du daemon et à
   l'activation du réglage auto-sync via `configure_skills`) ; sinon il
   faut confirmer dans l'UI. C'est conforme à `docs/library/USAGE.md` (§2–3),
   mais pas à une lecture littérale de « dès l'activation ».
2. **Énoncé 9 — suppression du code rendu mort non automatisée par changement.**
   Le garde-fou PC5 (vulture + knip) détecte le code mort restant, et deux cas
   sont documentés (réexport `library_merge`, export `shareValueHtml`), mais
   rien ne vérifie mécaniquement, à chaque changement, que le code devenu mort
   a bien été supprimé dans le même changement.
3. **Énoncé 2 — gate anti-dérive non exécuté en CI sur le dépôt réel.**
   `studio-client adapters check --project-id <id>` compare les projections
   versionnées à la Library active, mais la CI ne lance que les tests unitaires
   de `check_adapters` ; la comparaison réelle reste une commande locale/daemon.
4. **Énoncé 10 — couverture partielle du contrôle de code mort.** Ni le CSS, ni
   le Rust de `desktop/src-tauri`, ni le sidecar Python du desktop ne sont
   analysés ; `tests/`, `scripts/`, `docs/`, `examples/` et `contracts/` sont
   hors périmètre ; la liste blanche de `scripts/deadcode_whitelist.py` masque
   par nom (un nouveau symbole homonyme mort passe).
5. **Énoncé 5 — portée de « tous les utilisateurs ».** Le scope `studio` est
   lisible par tout membre d'au moins un projet ; un compte sans membership ne
   reçoit pas le commun (règle DEC-0103, pas un défaut).
6. **Énoncé 6 — « privés » sauf admin.** Une ressource `user` est invisible aux
   autres utilisateurs (404), mais l'admin peut la lire (DEC-0063).
7. **Piste `library_equivalence` absente.** Le nom cité dans le brief n'existe
   nulle part dans le code de ce worktree (`grep` : 0 occurrence) ;
   l'équivalence est répartie entre
   `adapters_check.check_adapters` (projections) et `drift.classify_state`
   (états de dérive).
