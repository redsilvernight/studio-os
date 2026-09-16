---
id: DEC-0039
title: 'Etape 7 (roadmap) : scenario "replay offline complet" ferme, outbox generique
  sans ajout client'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:1563537527fb77a5b5c8bd46abf6bd06ed040e1ece08f533edf8bca571b766ad
graphify_entities:
- kind: function
  node_id: tests_client_test_offline_replay_acceptance_test_full_offline_replay_tasks_events_ai_work_is_lossless_and_idempotent
  path: tests/client/test_offline_replay_acceptance.py
  project: studio-os
  relation: implements
  symbol: test_full_offline_replay_tasks_events_ai_work_is_lossless_and_idempotent
---

# DEC-0039 — Etape 7 (roadmap) : scenario "replay offline complet" ferme, outbox generique sans ajout client

Suite de DEC-0038 ("Terminer honnetement l'etape 7"). Analyse d'architecture
prealable (`studio-architect`) : test pur, aucun contrat touche — pas de
`contract-guardian` necessaire.

### Probleme

`docs/ROADMAP_CORRECTIONS_AUDIT.md` etape 7 listait "replay offline complet
avec tasks, events et AIWorkLog" comme scenario "Tests bout-en-bout" encore
ouvert. Le serveur (Bloc A) a `AIWorkLog` complet
(`services/api/src/studio_api/db/models/ai_work.py`, `routers/ai_work.py`,
`services/ai_work.py`) mais le client (Bloc B) n'a aucune reference a
`AIWorkLog` : aucune methode `StudioApiClient`, aucune commande CLI.

### Decision

Verifie par lecture que l'outbox/replay du client
(`packages/studio-client/src/studio_client/outbox/`) est deja totalement
generique : `OutboxStore.enqueue_mutation(idempotency_key, kind, method, path,
payload)` ne connait aucun domaine, et `OutboxReplayer._send` rejoue
`method`/`path`/`payload` tels quels via `send_mutation`. Aucun ajout cote
client n'etait donc necessaire pour fermer ce scenario — un vrai chemin
`create_ai_work`/CLI resterait un ajout purement additif pour l'etape 8 (AI
Work Ledger), pas un prealable a ce test.

Nouveau test `tests/client/test_offline_replay_acceptance.py`, meme discipline
que DEC-0038 (Postgres reel, transport ASGI in-process pour l'API, aucun
mock) :

- serveur injoignable simule par un `httpx.MockTransport` qui leve un vrai
  `httpx.ConnectError` sur chaque requete (jamais un stub applicatif) ;
- mise en queue directe via `OutboxStore` (3 `task.create`, 2 events dont un
  `ai_work.started`, 1 `ai_work.create`), chaque enqueue dans la meme
  transaction SQLite que l'ecriture locale qu'elle represente
  (`.claude/rules/offline-sync.md`) ;
- premier `replay_ready()` hors ligne : aucune perte, `stopped_on_transient_
  error` vrai, les 6 lignes restent en attente ;
- redemarrage simule (nouvelles instances `OutboxStore`/`StudioApiClient` sur
  le meme fichier SQLite) puis reconnexion reelle : les 6 operations
  arrivent en Postgres reel (3 tasks, 2 events, 1 entree `AIWorkLog`) ;
- rejeu integral des memes operations (memes `event_id`/`idempotency_key`) :
  aucun doublon, meme ligne `AIWorkLog` retrouvee par id.

Fixture `agent` ajoutee a `tests/client/conftest.py` (absente jusqu'ici cote
client ; `AIWorkLogModel.agent_id` et l'identite `actor_type="agent"` d'un
event l'exigent), copiee du meme pattern que `tests/api/conftest.py`.

Etape 7 mise a jour (`docs/ROADMAP_CORRECTIONS_AUDIT.md`) : ce scenario passe
de "encore ouvert" a ferme. Seul reste "deux machines simulees sur des
reseaux distincts" — hors perimetre de ce lot.

### Consequences

Aucune. Test pur et une fixture de test ajoutes, aucun code de production
modifie, aucun contrat touche.

### Preuves

`uv run pytest tests/client/test_offline_replay_acceptance.py -v` : 1 passed
(~1s), Postgres reel (conteneur Docker local `studio-test-pg`, port 5432).
`uv run pytest tests/client/ -q` : 130 passed (suite complete du package
client, aucune regression). `uv run ruff check
tests/client/test_offline_replay_acceptance.py tests/client/conftest.py` :
All checks passed.
