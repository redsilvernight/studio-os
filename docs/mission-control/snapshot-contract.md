# Snapshot d'exécution — contrat minimal (DEC-0199)

Enregistrement immuable de la configuration effective d'un run (une tentative
`TaskLaunch`). Contrat : `packages/studio-contracts/src/studio_contracts/execution_snapshot.py`
(`schema_version = 1`). Stockage : table `execution_snapshots` (migration 0032).
Service : `services/api/src/studio_api/services/execution_snapshots.py`. Routes
`POST`/`GET /api/v1/task-launches/{id}/snapshot`. Capture côté daemon :
`studio_client/daemon/launch_snapshot.py` (P04-snapshot-capture).

## Champs

Payload haché (`ExecutionSnapshotPayload`) :

| Champ | Contenu |
|---|---|
| `schema_version` | `1` ; toute autre valeur est refusée à la lecture |
| `capture_status` | `ok` \| `partial` \| `failed` |
| `resolution` | projection de la sortie du resolver commun : `agent_stable_key`, `profile` (clé, `contract_version`, digest), `resources[]` (rôle, `resource_id`, kind, `stable_key`, scope, version, `version_origin`, `content_digest`), `runtime` (niveau, clé appariée, `runtime_id`, `runtime_binding_id`, refs harness/provider/modèle, digest des capacités) |
| `applied` | paramètres appliqués par Bloc B : `harness_id`, `harness_version`, `projections[]` (cible logique relative + digest), `git_sha`, `git_dirty`, `local_policy_digest` ; additifs : `worktree_branch` (branche lue par git), `profile` (pin recalculé au démarrage), `access_mode` (mode imposé, `null` si refus) |
| `capture_errors[]` | codes fermés (`resolution_unavailable`, `git_sha_unavailable`, `worktree_unverified`, `redaction_required`…), champ concerné, détail court |

`resolution.profile` est le pin vu à la preview/admission, `applied.profile` celui
recalculé au démarrage : `ExecutionSnapshotPayload.profile_drift` expose l'écart.

Colonnes de la ligne : `id`, `project_id`, `task_launch_id` (unique), `content_hash`,
`schema_version`, `capture_status`, `capture_reason` (codes d'erreur triés, NULL si
`ok`), `payload` (JSONB), `created_at`, `retention_until`.

## Identité, immutabilité, déduplication

- `content_hash = "sha256:" + sha256(JSON canonique)` : clés triées, séparateurs
  compacts, UTF-8. Le payload ne contient pas l'id du launch : une même
  configuration a le même hash d'un launch à l'autre (index `content_hash`).
- Un snapshot par tentative. Ré-enregistrer le même contenu renvoie le snapshot
  existant (idempotent, sûr en concurrence via `ON CONFLICT DO NOTHING`) ; un
  contenu différent pour le même launch est refusé (`409 execution_snapshot_immutable`).
  Le service n'émet jamais d'`UPDATE` du payload.
- Aucune FK vers les ressources Library ni les RuntimeBindings : supprimer ou
  archiver une ressource courante ne modifie pas un snapshot.
- `ok` exige `resolution` et `applied` sans erreur ; `partial` et `failed` exigent au
  moins une erreur explicite. Rien n'est omis silencieusement.

## Redaction

- Références et empreintes uniquement : contenus de règles, skills, prompts et
  fichiers projetés sont réduits à un digest (`digest_of`). `resolution_refs`
  projette un `ResolvedAgentDefinition` déjà résolu, sans second resolver.
- Chaque chaîne du payload est contrôlée (`contains_secret_material`,
  `contains_absolute_path` de `studio_contracts.local.common`) ; un nom de champ
  secret est refusé ; champs inconnus interdits (`extra="forbid"`).
- Pas de masquage silencieux : une valeur suspecte fait échouer la validation. La
  capture doit alors produire `redaction_required` sans la valeur.
- Payload canonique plafonné à 256 Kio (`snapshot_payload_too_large`).

## Capture (daemon)

- Une capture par lancement, au point le plus tardif atteint : juste avant le
  report `running` ; sinon au refus du profil (`git_sha_unavailable`, détail
  `profile_refused`) ; sinon à l'échec de préparation (`preparation_failed:<étape>`).
  Rien si le lancement n'est pas résolu ou devient terminal avant le démarrage.
- `git_sha`, `git_dirty` et `worktree_branch` sont lus par git dans le worktree
  (`rev-parse --show-toplevel`, `rev-parse HEAD`, `status --porcelain`,
  `symbolic-ref`), jamais repris de la préparation ; écart → `worktree_unverified`.
- `resolution` vient de `resolve_agent` (lecture pure) projeté par
  `resolution_refs` ; sans `agent_stable_key` → `resolution_unavailable`.
- Projections : digest des fichiers gérés par le bootstrap, lus après préparation.
- Valeur suspecte (secret, chemin absolu) : retirée et nommée par
  `redaction_required`, jamais journalisée ; les logs ne portent que le statut.
- Envoi par l'outbox, clé stable par lancement : un rejeu ne crée ni seconde
  ligne locale ni second snapshot serveur.

## Rétention

`retention_until = created_at + STUDIO_EXECUTION_SNAPSHOT_RETENTION_DAYS` (défaut
**90 jours**, borné 1–3650 ; surcharge possible par appel). `purge_expired` supprime
par lots de 1000 les lignes échues et renvoie le nombre supprimé ; aucune tâche
planifiée n'est encore branchée.

## Lecture et export

`get_snapshot(id)` et `get_snapshot_for_launch(launch_id)` revalident le payload
contre le contrat. L'export est le JSON canonique du payload, vérifiable en
recalculant `content_hash`. `GET /task-launches/{id}/snapshot` : lecture en portée
projet ; `POST` : machine cible seule (règles du report).

## Limites

- Rejouer les paramètres enregistrés ne garantit pas de reproduire la sortie IA
  (modèle non déterministe, état du dépôt, services externes).
- Les digests prouvent l'identité d'un contenu, pas sa récupération : une version
  Library purgée ne peut pas être reconstruite depuis le snapshot.
- La détection de secrets est heuristique ; elle complète la règle structurelle
  (aucun champ secret dans le contrat), sans la remplacer.
