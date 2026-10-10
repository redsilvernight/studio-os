# Mission Control — read model (P02-read-model)

Projection de lecture bornée des exécutions d'un projet, calculée à la
lecture et jamais persistée. Contrat figé :
[mission.py](../../packages/studio-contracts/src/studio_contracts/mission.py).
Décisions : DEC-0196 (read model), DEC-0201 (protocole distinct du
processus). Route HTTP : [02_API_CONTRACT.md](../Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md), section Mission
Control. Mesures : [metrics.md](metrics.md).

## Objet

Exposer, par exécution, un verdict affiché tel quel par les clients
(`MissionVerdict`), les raisons qui l'ont produit (`MissionReason`),
l'état de clôture du protocole (`MissionProtocolState`) et les données
manquantes (`MissionDataGap`). Le serveur applique la table de vérité
ci-dessous et renvoie le verdict ; les clients affichent le verdict et
ne le re-dérivent jamais. Ils doivent tolérer un `verdict` ou une
`reason` inconnus (vocabulaires additifs uniquement).

## Sources

Uniquement des sources existantes, sans nouvelle entité ni état
parallèle : `TaskLaunch`, `WorkSession`, `AIWorkLog`, claims de
ressources (expirées exclues, même filtre que le service claims),
machines et décisions proposées liées à la tâche.

Un `MissionRun` par `TaskLaunch`, plus un par `WorkSession` qu'aucun
lancement ne référence (sessions manuelles, `source: session`).

## Table de vérité

Évaluée de haut en bas, premier match gagnant. `reasons` liste **tous**
les motifs correspondants (pas seulement le gagnant) pour qu'un état
discordant reste visible ; la première entrée est la ligne gagnante.

| # | Condition | Verdict | Reason |
|---|---|---|---|
| 1 | Lancement `cancelled` | `cancelled` | `launch_cancelled` |
| 2 | Lancement `failed` / `rejected` / `expired` | `failed` | `launch_failed` / `launch_rejected` / `launch_expired` |
| 3 | `AIWork` en `review_requested` sur la session (sur la tâche si pas de session) | `waiting_human` | `review_requested` |
| 4 | Décision proposée liée à la tâche | `waiting_human` | `decision_proposed` |
| 5 | Protocole `handed_off` | `done` | `handed_off` |
| 6 | Lancement `succeeded`, sans session | `needs_attention` | `process_exited_without_session` |
| 7 | Lancement `succeeded`, session terminée sans handoff | `needs_attention` | `session_ended_without_handoff` |
| 8 | Lancement `succeeded`, session ouverte | `needs_attention` | `process_exited_session_open` |
| 9 | Session `expired`, ou machine `offline` pendant que le lancement ou la session est ouvert | `stale` | `session_expired` / `machine_offline` |
| 10 | Pas de lancement, session terminée sans handoff | `needs_attention` | `session_ended_without_handoff` |
| 11 | Lancement `requested` / `accepted` / `preparing` | `pending` | `launch_pending` |
| 12 | Sinon (lancement `running`, session `active` / `idle`) | `running` | `process_running` / `session_idle` |

## Protocole vs processus (DEC-0201)

La fin du processus (statut du lancement) et la clôture du protocole
(session terminée **avec** une entrée de handoff) sont rapportées
séparément : `exit_code == 0` seul ne donne jamais `done`.
`protocol_state` vaut `open` (session non terminée), `handed_off`
(session terminée avec une entrée `AIWork` non-`started` liée, ce
qu'écrit `studio_handoff`), `ended_without_handoff` (session terminée
sans une telle entrée) ou `missing` (pas de session). Seule la ligne 5
(`handed_off`) produit le verdict `done`.

## Données incomplètes (`data_gaps`)

Explicitement incomplet, jamais comblé par une valeur fabriquée :
`machine_unknown`, `session_not_found`, `task_not_found`.

## Pagination et fenêtre

`window_hours` (défaut 168, max 720), `limit` (défaut 20, max 50),
`cursor` opaque. Réponse `ProjectMission` : `runs` (page courante),
`counts` (comptes par verdict **sur toute la fenêtre**, pas seulement
la page), `generated_at`, `next_cursor` (`null` en fin de liste) et
`truncated` (vrai si la fenêtre a été tronquée par les bornes).

## Bornes

`MISSION_DEFAULT_LIMIT = 20`, `MISSION_MAX_LIMIT = 50`,
`window_hours ≤ 720`. Compteurs `counts.by_verdict` et `counts.total`
portent sur tous les runs de la fenêtre.

## Aucun état persistant

Lecture pure : aucun calcul stocké, aucune nouvelle entité de session,
aucun second état parallèle. Les claims expirés ne sont jamais
comptés. Un rejeu à paramètres égaux sur des sources inchangées rend
le même verdict.
