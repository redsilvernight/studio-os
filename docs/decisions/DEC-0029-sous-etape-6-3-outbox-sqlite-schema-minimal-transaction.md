---
id: DEC-0029
title: 'Sous-etape 6.3 (outbox SQLite) : schema minimal, transaction laissee a l''appelant,
  backoff sans abandon'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:6819c990e33eb7d64304344b439f8755d807bd7c579a8ca59f0622962f61815e
graphify_entities:
- kind: class
  node_id: OutboxStore
  path: packages/studio-client/src/studio_client/outbox/store.py
  project: studio-os
  relation: implements
  symbol: OutboxStore
- kind: class
  node_id: PendingRow
  path: packages/studio-client/src/studio_client/outbox/models.py
  project: studio-os
  relation: implements
  symbol: PendingRow
- kind: class
  node_id: OutboxTable
  path: packages/studio-client/src/studio_client/outbox/models.py
  project: studio-os
  relation: implements
  symbol: OutboxTable
---

# DEC-0029 — Sous-etape 6.3 (outbox SQLite) : schema minimal, transaction laissee a l'appelant, backoff sans abandon

Etudie sans `studio-architect` (meme principe que 6.2 : perimetre isole,
stockage local pur, aucune frontiere de contrat/Bloc A-Bloc B nouvelle).

### Probleme

`docs/ROADMAP_STEP6_BREAKDOWN.md` sous-etape 6.3 et `.claude/rules/offline-sync.md`
exigent une file locale persistante avant qu'un daemon/CLI/watcher (6.4-6.6)
puisse ecrire quoi que ce soit sans risquer une perte silencieuse pendant une
coupure reseau — invariant projet "les clients doivent tolerer l'offline et
rejouer les ecritures de facon idempotente". Rien de tel n'existait dans
`packages/studio-client/`.

### Decision

- `packages/studio-client/src/studio_client/outbox/` : `models.py`
  (`OutboxTable` StrEnum, `PendingRow` dataclass generique) et `store.py`
  (`connect()`, `transaction()`, `OutboxStore`, `default_outbox_path()`).
- Schema SQLite minimal exige par la sous-etape : `pending_events`,
  `pending_mutations`, `pending_markers`, `sync_state`, `dead_letter`.
  `PRIMARY KEY` sur la cle d'idempotence/event_id de chaque table
  replayable (`event_id`, `idempotency_key`, `marker_id`) — l'`INSERT OR
  IGNORE` fait l'idempotence, le rowcount distingue insertion reelle vs
  doublon ignore.
- Aucune methode `enqueue_*` ne commite elle-meme : la frontiere
  transactionnelle est decidee par l'appelant (nu, ou via `transaction()`,
  qui commite au succes et rollback sur toute exception) — c'est ce qui
  permet a un futur appelant (CLI/watcher, 6.4-6.6) d'inserer une ligne
  outbox dans la MEME transaction SQLite que l'ecriture locale qu'elle
  represente, jamais une transaction separee et plus tardive (exigence
  explicite de la regle offline-sync).
- Cle d'idempotence/`event_id` toujours fournie par l'appelant, jamais
  generee par le store (meme invariant que `StudioApiClient`, DEC-0024).
- `mark_failed` reutilise `RetryPolicy.delay_for` (`retry.py`, DEC-0024)
  pour le calcul du delai — borne par `backoff_max` — mais n'abandonne
  jamais uniquement sur le nombre de tentatives : seul un appel explicite
  a `move_to_dead_letter` (echec definitif, non transitoire) sort une
  ligne de la queue rejouable. La distinction retryable/definitif
  elle-meme (via `is_retryable`) est laissee a la logique de replay de la
  sous-etape 6.4, hors perimetre ici.
- `move_to_dead_letter` copie la ligne entiere en JSON avant suppression —
  jamais seulement l'id, pour rester inspectable.
- `sync_state` : table cle/valeur JSON generique, sans usage pour l'instant
  (reservee au curseur/etat de reprise de la sous-etape 6.4).
- `default_outbox_path()` : sibling de `config.default_config_path()`
  (meme base par OS), pas encore branche dans `ClientConfig` — aucun
  appelant reel (daemon/CLI) ne l'utilise dans ce lot, prematuré d'ajouter
  un champ de configuration sans consommateur.

### Consequences

Aucun changement de contrat, aucune nouvelle dependance (`sqlite3` est
stdlib). Limite connue signalee par `studio-tester`, non corrigee ici : les
paires lecture-puis-ecriture (`SELECT` puis `UPDATE`/`DELETE`) de
`mark_failed`/`move_to_dead_letter` ne sont pas atomiques — sans consequence
en usage mono-thread/mono-processus actuel (aucun appelant concurrent
n'existe encore), mais a garder en tete pour la logique de replay de la
sous-etape 6.4 si elle devient multi-thread/multi-processus sur le meme
fichier SQLite.

### Preuves

`packages/studio-client/src/studio_client/outbox/{__init__,models,store}.py`,
`tests/client/test_outbox.py` (11 tests : idempotence des trois kinds
d'enqueue par doublon de cle, redemarrage — fermeture/reouverture de la
connexion sur le meme fichier — ne perd aucune ligne en attente, atomicite
transaction/rollback conjoint avec une ecriture locale simulee, backoff
borne par `backoff_max` sans abandon sur le compteur, `dead_letter`
retire la ligne de la queue et conserve le payload complet, `sync_state`
round-trip). Revue independante `studio-tester` : aucun bug bloquant trouve
(schema, transaction, idempotence, typage coherents avec les contrats),
une limite non bloquante signalee (ci-dessus, Consequences) et
deliberement non corrigee car hors perimetre du diff. Suite
`tests/client/` complete : **59 passed** (48 existants + 11 nouveaux).
Suite complete du depot (Postgres 16 + MinIO reels) : **176 passed**,
aucun echec. `ruff check .`, `ruff format --check .` (200 fichiers) et
`mypy packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` (strict) verts (90 fichiers). Les deux
suivis rejouees independamment par `studio-tester` avec les memes
resultats.
