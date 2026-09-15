---
id: DEC-0030
title: 'Sous-etape 6.4 (replay ordonne) : fusion chronologique events+mutations, arret
  sur transitoire, markers hors perimetre'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:0e5e963376e7b6507217af387e962139128e856b1062d686c02c07bf9761e932
graphify_entities:
- kind: class
  node_id: OutboxReplayer
  path: packages/studio-client/src/studio_client/outbox/replay.py
  project: studio-os
  relation: implements
  symbol: OutboxReplayer
- kind: class
  node_id: ReplayOutcome
  path: packages/studio-client/src/studio_client/outbox/replay.py
  project: studio-os
  relation: implements
  symbol: ReplayOutcome
---

# DEC-0030 — Sous-etape 6.4 (replay ordonne) : fusion chronologique events+mutations, arret sur transitoire, markers hors perimetre

Etudie sans `studio-architect` (meme principe que 6.2/6.3 : perimetre
isole, aucune frontiere de contrat/Bloc A-Bloc B nouvelle — reutilise
`StudioApiClient.post_event`/nouvelle methode generique du meme client).
Prealable de la roadmap (ecart residuel DEC-0023/0024, `studio_emit_event`
generant lui-meme `event_id`) deja tranche par DEC-0027 avant ce lot —
aucun travail supplementaire necessaire ici.

### Probleme

L'outbox (6.3) accumule des lignes en attente mais rien ne les rejoue :
sans drainage, une coupure reseau vide la queue dans le vide plutot que de
la reconcilier une fois le serveur de nouveau joignable — contredit
l'invariant offline-sync. Il fallait aussi decider comment detecter une
reconnexion sans dupliquer un etat deja porte par le backoff par ligne.

### Decision

- `packages/studio-client/src/studio_client/outbox/replay.py` :
  `OutboxReplayer.replay_ready()` fusionne `pending_events` et
  `pending_mutations` en une seule liste triee par `created_at` croissant
  (jamais un tri separe par table), puis rejoue strictement dans cet
  ordre — c'est la fusion, pas un mecanisme de session/tache dedie, qui
  preserve l'ordre inter-tables exige par `.claude/rules/offline-sync.md`.
- Sur une erreur retryable (`is_retryable()`, `retry.py`, DEC-0024) : la
  ligne repart en `mark_failed` (backoff borne) ET **toute la passe
  s'arrete immediatement** — jamais de ligne suivante envoyee avant
  qu'une ligne anterieure en echec transitoire n'ait reussi, seule facon
  simple de garantir l'ordre sans grouper par session/tache.
- Sur une erreur non retryable (business, ex. 404/409 metier) : la ligne
  part en `dead_letter` et **la passe continue** — elle est resolue de
  maniere definitive, pas bloquante pour les lignes suivantes.
- `StudioApiClient.send_mutation()` (nouvelle methode, `api_client.py`) :
  rejoue une ligne `pending_mutations` generique (method/path/payload
  stockes tels quels) avec le meme contrat idempotent que
  `create_task`/`post_event` (`Idempotency-Key` header, `idempotent=True`).
- Detection de reconnexion : pas d'etat "hors-ligne" separe suivi par le
  daemon. Un heartbeat reussi EST le signal — `HeartbeatDaemon.run()`
  appelle `replay_ready()` uniquement dans la branche de succes du
  heartbeat, jamais apres un echec (`replayer` optionnel, `None` par
  defaut : aucun changement de comportement pour un appelant existant).
  Un cablage separe d'un etat "etait hors-ligne" aurait seulement duplique
  ce que le backoff par ligne de l'outbox fait deja.
- `pending_markers` explicitement **hors perimetre de ce lot** : aucun
  routeur HTTP ni outil MCP ne consomme un objet marker aujourd'hui
  (`rg -i marker services/api/src services/mcp/src
  packages/studio-contracts/src` ne retourne que la valeur d'enum
  `EventType.RECORDING_MARKER_CREATED`) — rejouer cette table aurait
  exige d'inventer une cible serveur. Les lignes marker restent en file,
  intactes ; `OutboxReplayer` ne les touche jamais. A trancher quand une
  sous-etape future (enregistrements) definira leur cible reelle.

### Consequences

Aucun changement de contrat, aucune nouvelle dependance. Deux limites non
bloquantes signalees par `studio-tester`, non corrigees ici (hors
perimetre du diff) :
- une ligne `pending_events`/`pending_mutations` malformee (cle `extra`
  manquante, JSON incoherent) leve une exception non-`StudioApiError`
  a travers `replay_ready()`/`_replay_outbox()`, non interceptee — tue
  la boucle du daemon entiere plutot que de dead-letter la seule ligne
  fautive. Ne devrait pas se produire via `enqueue_event`/
  `enqueue_mutation` (colonnes `NOT NULL`), mais rien ne le garantit au
  niveau du replay lui-meme ;
- l'ordre n'est garanti que **dans** une passe (le `break` empeche de
  depasser une ligne anterieure) ; entre deux passes, une ligne en
  backoff plus long que l'intervalle entre deux heartbeats peut sortir de
  `list_pending(ready_only=True)` et laisser passer une ligne plus
  recente devant elle. Les valeurs par defaut actuelles
  (`heartbeat_interval_seconds=30`, `backoff_max=20`) laissent toujours
  de la marge, mais rien dans le code ne le garantit si ces valeurs
  changent.

### Preuves

`packages/studio-client/src/studio_client/outbox/replay.py`,
`api_client.py::send_mutation`, `daemon/heartbeat.py` (parametre
`replayer` optionnel). `tests/client/test_replay.py` (6 tests : fusion
chronologique events+mutations, reconstruction fidele du payload d'un
event rejoue, dead-letter + continuation sur erreur non retryable, arret
de la passe + preservation d'ordre sur erreur transitoire, markers jamais
touches, passe vide = no-op) et `tests/client/test_daemon.py` (+2 tests :
replay declenche apres heartbeat reussi, jamais apres heartbeat en echec).
Suite `tests/client/` : **67 passed** (59 existants + 8 nouveaux). Suite
complete du depot (Postgres 16 + MinIO reels) : **184 passed**, aucun
echec. `ruff check .`, `ruff format --check .` (202 fichiers) et
`mypy packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` (strict, commande CI reelle) verts (91
fichiers). Revue independante `studio-tester` : aucun bug bloquant trouve,
verdict clos, les deux limites ci-dessus consignees comme non bloquantes.
