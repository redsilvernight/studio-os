# P00-repro : écarts de synchro Library reproduits

Tests : `tests/client/test_library_p00_repro.py` (5 `xfail(strict=True)` + 1 mesure paramétrée). Chemins relatifs à la racine. Les écarts sont **déduits du code** (aucune liste fournie) ; les hypothèses sont marquées.

## Écarts retenus

| # | Écart | Preuve | Comportement actuel | Test xfail |
|---|---|---|---|---|
| 1 | Pas de resynchro après activation d'une version | `packages/studio-client/src/studio_client/daemon/skills_bridge.py:1210,1222` (`_started`), `daemon/runtime.py:549` (seul appel au démarrage) | Le runner ne tourne qu'une fois ; un second `start()` est un no-op. Rien n'écoute `library.version.activated` (cf. P00-events.md). | `test_runner_resyncs_when_a_new_version_is_activated` : v2 jamais écrite, le fichier reste en v1 |
| 2 | Listing tronqué à 100 lignes, sans pagination | `skills_bridge.py:80` (`_SKILL_LIMIT = 100`), `:679`; `context/library.py:121,180` (aucun `offset`) ; serveur `le=500` (`services/api/src/studio_api/routers/library.py:63`) | Avec 150 ressources, 117 projections reviennent ; le reste est ignoré sans erreur ni statut. | `test_sync_projects_every_resource_beyond_one_listing_page` (117 != 150) |
| 3 | Un conflit local bloque toute la synchro | `skills_bridge.py:1259` (auto), `:1070` (apply) | Un seul fichier modifié : statut `CONFLICTS`, aucun autre élément appliqué, rien de persisté sur le choix de garder l'override local. | `test_conflict_on_one_item_does_not_block_the_others` |
| 4 | Champs perdus à la publication | `publish.py:107` (rule : `text` seul), `:118` + `canonical.py:494-505` (agent : `summary`, `intended_use` seuls) | `applies_to` des rules ; `instructions`, `triggers`, `edit_policy`, `tools` des agents absents du contenu Library (voir P00-inventory.md §3). | `test_published_rule_keeps_applies_to`, `test_published_agent_keeps_instructions_and_edit_policy` |

Hypothèses : (3) contredit volontairement `tests/client/test_daemon_library_sync.py::test_local_conflict_blocks_every_kind_and_stays_visible`, qui fige le blocage global actuel ; le comportement cible (application partielle, override local conservé) est à valider. (1) le test utilise `runner.start()` comme déclencheur, faute d'API de relance ; P20 pourra l'adapter. La « durabilité » des conflits n'est pas testée séparément.

## Requêtes mesurées

Mesure réelle : `test_requests_per_sync_for_n_resources`, client HTTP simulé (`httpx.MockTransport`) branché sur `skills_bridge.StudioApiClient`. N ressources `studio` réparties à parts égales sur rule / skill / agent_definition, une exécution de `_AutoSyncRunner._run` sur un home vide. Le batch (50 versions par appel) est déjà en place.

| N | `GET /library` | `POST batch-get` | Total / synchro |
|---|---|---|---|
| 10 | 2 | 2 | 4 |
| 50 | 2 | 2 | 4 |
| 100 | 2 | 3 | 5 |

- Une synchro sans changement coûte autant (aucun fetch conditionnel, pas d'ETag).
- `preview_skills` refait le même fetch complet (assertion du test) ; `apply_skills` aussi (`skills_bridge.py:913-915`, non mesuré). Un parcours aperçu puis application coûte donc au moins 2 fois ce total.
- Au-delà de 100 ressources listées, le coût cesse d'être représentatif : voir écart 2.

## `notifyIfChanged` (`dashboard/src/skillsSync.ts:167`)

Appelée depuis le polling local `skills.status` (`:337`, quand `notify` est vrai). Elle :
1. sort si la boîte de dialogue de détail est ouverte (`DIALOG_ID` non masqué) ;
2. sort si l'état vaut `in_progress`, `up_to_date` ou `disabled` ;
3. calcule la clé `état|last_check` et la compare à `localStorage["studio.skills-sync.notified"]` (`:25`) : même clé = pas de nouvelle notification, sinon elle la stocke (échec du stockage ignoré, le toast peut alors se répéter) ;
4. affiche un toast : `updated` = « N élément(s) ajouté(s) ou mis à jour » (succès), `conflicts` = « N conflit(s) à résoudre » (avertissement), autre (`not_synced`) = « non synchronisée » (avertissement), puis marque le toast `data-skills-notice`.

Conséquence : elle ne notifie que ce que le daemon a écrit dans son statut ; sans resynchro (écart 1), aucune nouvelle version n'est jamais signalée. Chaque nouveau run change `last_check`, donc un état `conflicts` ou `not_synced` re-notifie à chaque run.

## Exécution

`pytest tests/client/test_library_p00_repro.py --noconftest` : 3 passed, 5 xfailed. `--noconftest` car le conftest de `tests/client` exige PostgreSQL (non démarré ici) ; le `PYTHONPATH` pointait sur les sources du worktree (le venv racine résout `studio_client` vers le checkout principal, plus ancien, sans batch). Non validé : exécution avec le conftest et l'infra.
