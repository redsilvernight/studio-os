---
id: DEC-0018
title: 'Realtime (roadmap etape 4.1) : SSE + curseur `seq`, pas de WebSocket'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:46e9d4810ac44e511e1a3bf0dbd8b97fe6e20879b6362bf815e5fdd2c6e35207
graphify_entities:
- kind: class
  node_id: services_api_src_studio_api_services_event_stream_streamevent
  path: services/api/src/studio_api/services/event_stream.py
  project: studio-os
  relation: implements
  symbol: StreamEvent
- kind: function
  node_id: services_api_src_studio_api_services_event_stream_publish
  path: services/api/src/studio_api/services/event_stream.py
  project: studio-os
  relation: implements
  symbol: publish
- kind: function
  node_id: services_api_src_studio_api_services_event_stream_subscribe
  path: services/api/src/studio_api/services/event_stream.py
  project: studio-os
  relation: implements
  symbol: subscribe
- kind: function
  node_id: services_api_src_studio_api_routers_events_stream_events
  path: services/api/src/studio_api/routers/events.py
  project: studio-os
  relation: implements
  symbol: stream_events
- kind: file
  node_id: services_api_alembic_versions_0004_events_seq_identity
  path: services/api/alembic/versions/0004_events_seq_identity.py
  project: studio-os
  relation: concerns
  symbol: 0004_events_seq_identity.py
- kind: class
  node_id: services_api_src_studio_api_db_models_event_eventmodel
  path: services/api/src/studio_api/db/models/event.py
  project: studio-os
  relation: concerns
  symbol: EventModel
---

# DEC-0018 — Realtime (roadmap etape 4.1) : SSE + curseur `seq`, pas de WebSocket

`TECH/03_EVENT_CONTRACT.md` ne tranchait pas de transport ;
`TECH/02_API_CONTRACT.md` ne faisait que nommer un `/api/v1/stream` sans
mecanisme. Retenu : Server-Sent Events (`GET /api/v1/events/stream`), pas
WebSocket, pas de long-polling nu.

Justification :
- Le canal est unidirectionnel par nature (le serveur pousse des events, les
  ecritures Bloc B passent deja par les endpoints REST existants) — WebSocket
  ajouterait une negociation bidirectionnelle et un keep-alive ping/pong pour
  un besoin qui n'en a pas.
- La reprise apres coupure est native au protocole SSE (header
  `Last-Event-ID`, champ `id:` par event), ce qui couvre directement le
  critere d'acceptation "pas de perte, pas de doublon" sans inventer un
  protocole de reprise maison.
- Caddy (`reverse_proxy`) relaie SSE comme n'importe quelle reponse HTTP en
  streaming, sans directive dediee ; pas de handshake d'upgrade a gerer.
- Cout de test plus faible qu'un WebSocket en theorie ; en pratique,
  `httpx.ASGITransport` (utilise par le fixture `client` existant) bufferise
  tout le corps de la reponse avant de rendre la main a l'appelant — decouvert
  a l'implementation, cf. `httpx/_transports/asgi.py::handle_async_request`,
  `await self.app(...)` est attendu en entier avant de construire la
  `Response`. Un flux SSE reellement sans fin ne se termine jamais, donc ce
  transport bloque indefiniment dessus, quel que soit le transport choisi
  (le meme probleme se serait pose pour un WebSocket). Contourne par un
  serveur `uvicorn` reel sur `localhost` pour les seuls tests de
  `GET /events/stream` (fixtures `live_client`/`live_project_and_token`,
  `tests/api/test_events.py`) — vraies sockets, pas de tampon de corps
  complet. Consequence : ces tests utilisent le vrai moteur DB
  (`get_session_factory()`) plutot que la session a savepoint des autres
  tests (le serveur uvicorn tourne dans le meme process/event loop mais avec
  ses propres connexions, qui ne verraient jamais une ecriture non commitee) ;
  `studio_api/db/session.py::reset_engine()` ajoute pour disposer/reinitialiser
  le moteur mis en cache entre deux tests (chaque test pytest-asyncio a sa
  propre event loop, incompatible avec un pool de connexions asyncpg cree sur
  une loop precedente deja fermee).
- Aucune dependance ajoutee : `StreamingResponse` + generateur async
  suffisent, pas besoin de `sse-starlette`.

Curseur : `server_timestamp` n'est pas garanti strictement croissant/sans
collision a la microseconde sous ecriture concurrente. Ajout de
`events.seq`, colonne `BIGINT GENERATED ALWAYS AS IDENTITY`, unique
(migration `0004`). Le champ SSE `id:` est `str(seq)`. Une reconnexion
reprend a `seq > curseur`, curseur resolu dans l'ordre : header
`Last-Event-ID` (reprise automatique d'un client SSE standard) puis
query param `since_seq` (reprise explicite pour un client non-navigateur) ;
sans aucun des deux, le flux ne livre que les events créés a partir de la
connexion (pas de rejeu implicite de tout l'historique — `GET /events`
existant reste le canal de rattrapage explicite).

Diffusion : un hub en memoire par process (`studio_api/services/event_stream.py`),
alimente par `events_service.create_event` apres commit (jamais sur un
replay idempotent — l'event n'est pas nouveau). Limite connue : ceci suppose
une seule instance `api` (c'est le cas dans `docker/docker-compose.yml`,
aucune replication) ; passer a plusieurs instances exigerait `LISTEN/NOTIFY`
Postgres ou un bus externe — hors perimetre de cette sous-etape, a traiter si
un besoin reel de scale horizontal apparait. Un abonne qui ne consomme pas
assez vite (file bornee a 256) est deconnecte plutot que de bloquer les
autres ou de faire fuir la memoire ; il doit se reconnecter avec son dernier
`seq` vu, ce qui reste sans perte grace au rattrapage par curseur ci-dessus.

Autorisation : identique a `GET /events` existant — machine authentifiee
(`CurrentMachine`), pas de controle d'appartenance au projet au-dela de ce
qui existe deja ailleurs dans l'API (aucune ACL par projet n'est implementee
nulle part a ce jour ; en inventer une seule pour ce nouvel endpoint aurait
ete un invariant non demande par les contrats actuels).

Pas de changement incompatible du contrat Event (enveloppe inchangee,
`seq` est un detail d'implementation interne, jamais expose dans
`EventEnvelope`) ; `TECH/02_API_CONTRACT.md` mis a jour pour decrire le
mecanisme reel a la place du placeholder `/api/v1/stream`.
