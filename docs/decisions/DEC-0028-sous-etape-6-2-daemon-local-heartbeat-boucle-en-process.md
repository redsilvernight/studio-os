---
id: DEC-0028
title: 'Sous-etape 6.2 (daemon local, heartbeat) : boucle en process, sleep injectable,
  signaux best-effort'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:5795399b2921f1f49c7b2c62285b8560bfcca34d616468593d7c83d1fe9a5aeb
graphify_entities:
- kind: class
  node_id: packages_studio_client_src_studio_client_daemon_heartbeat_heartbeatdaemon
  path: packages/studio-client/src/studio_client/daemon/heartbeat.py
  project: studio-os
  relation: implements
  symbol: HeartbeatDaemon
- kind: class
  node_id: packages_studio_client_src_studio_client_config_clientconfig
  path: packages/studio-client/src/studio_client/config.py
  project: studio-os
  relation: extends
  symbol: ClientConfig
---

# DEC-0028 — Sous-etape 6.2 (daemon local, heartbeat) : boucle en process, sleep injectable, signaux best-effort

### Probleme

Aucun process long ne maintenait l'etat "cette machine est en ligne" :
`StudioApiClient.send_heartbeat` (DEC-0024) existait mais rien ne l'appelait
periodiquement. `docs/ROADMAP_STEP6_BREAKDOWN.md` sous-etape 6.2 exige un
intervalle configurable avec jitter (eviter un troupeau de heartbeats
synchronises entre postes), un arret propre sur signal sans perdre un
heartbeat en vol, et des tests sans vrai `sleep`.

### Decision

- `packages/studio-client/src/studio_client/daemon/heartbeat.py::HeartbeatDaemon` :
  boucle `while not stopped: send_heartbeat(); sleep(next_delay())`.
  `request_stop()` ne fait que positionner un `asyncio.Event` verifie entre
  deux iterations — jamais d'annulation d'un appel `send_heartbeat` deja en
  vol, donc pas de heartbeat partiellement envoye ni de reponse perdue.
- `sleep` est injectable (parametre constructeur, defaut `asyncio.sleep`),
  meme principe que `random_fn` (defaut `random.random`) — permet aux tests
  de piloter les iterations sans horloge reelle (le heartbeat tourne par
  defaut sur un intervalle de 30s, bien trop long pour un `sleep()` reel en
  suite de tests, contrairement au backoff de retry de
  `packages/studio-client/src/studio_client/retry.py` dont les valeurs de
  test restent de l'ordre de la milliseconde).
- Deux nouveaux champs `ClientConfig` (`heartbeat_interval_seconds=30.0`,
  `heartbeat_jitter_ratio=0.1`), surchargeables via `STUDIO_CLIENT_*` comme
  le reste de la config (DEC-0024) — le constructeur de `HeartbeatDaemon`
  accepte aussi des overrides explicites pour les tests et un futur usage CLI.
  Jitter applique symetriquement (`interval * (1 ± jitter_ratio)` via un
  `random_fn` injectable), pas seulement additif.
- `HeartbeatDaemon` exige `config.machine_id` (deja un champ optionnel de
  `ClientConfig` depuis DEC-0024, jusqu'ici jamais consomme) — leve
  `ValueError` explicite a la construction sinon, plutot qu'un
  `AttributeError`/`None` silencieux propage jusqu'au serveur.
- `install_signal_handlers(stop)` : `signal.signal` sur `SIGINT`/`SIGTERM`
  quand l'attribut existe, jamais `loop.add_signal_handler` — ce dernier
  leve `NotImplementedError` sur l'event loop Windows par defaut
  (`ProactorEventLoop`), or ce depot cible aussi des postes de developpeur
  Windows (pas seulement le VPS Linux). Livraison de `SIGTERM` reconnue
  peu fiable sous Windows dans le docstring — enregistrer le handler reste
  sans risque la ou il ne sert a rien.
- Nouveau point d'entree `studio-client-daemon`
  (`packages/studio-client/pyproject.toml`, `studio_client.daemon.heartbeat:main`)
  distinct de `studio-client` (CLI `login` existante, DEC-0024) : la CLI
  complete a commandes multiples est explicitement hors perimetre de cette
  sous-etape (reservee a 6.5, `docs/ROADMAP_STEP6_BREAKDOWN.md`) — un second
  script minimal evite de coupler prematurement le daemon a la structure de
  sous-commandes que 6.5 doit encore concevoir.
- Aucune dependance a un scheduler externe (`APScheduler` ou equivalent) :
  boucle asyncio nue, coherent avec le choix deja fait pour le worker
  d'expiration des transferts (DEC-0020) et les backups (DEC-0021).

### Revue independante (`studio-tester`, 2026-09-13)

Verdict initial : valide, non bloquant, avec une limitation reelle trouvee
(pas seulement suggeree) — `run()` attendait `await self._sleep(delay)` sans
jamais observer `_stop_event` pendant l'attente : un `request_stop()`
declenche pendant ce sleep (signal recu juste apres un heartbeat) ne
reveillait rien, la latence d'arret restant bornee par l'intervalle jitte en
cours (jusqu'a ~33s avec les valeurs par defaut), pas par le signal
lui-meme. Pas un abandon de heartbeat ni une corruption, mais contraire a
l'esprit d'un "arret propre" attendu par l'operateur d'un daemon. Corrige
dans la meme session : `_wait()` court desormais `self._sleep(delay)` et
`self._stop_event.wait()` en parallele (`asyncio.wait(...,
return_when=FIRST_COMPLETED)`), annule et draine la tache perdante — un
`request_stop()` interrompt l'attente immediatement au lieu d'attendre la
fin de l'intervalle, sans changer la garantie deja verifiee (le heartbeat
lui-meme, s'il est en cours, n'est jamais annule : `_wait` n'est appele
qu'apres son retour). Nouveau test de regression
`test_stop_during_wait_returns_promptly` (`tests/client/test_daemon.py`) :
intervalle reel de 5s, `request_stop()` appele pendant l'attente, `run()`
doit rendre la main sous 1s — echouerait a coup sur sur l'ancienne
implementation (`asyncio.wait_for(..., timeout=1.0)` expirerait avant que
le vrai `asyncio.sleep(5.0)` ne se termine). Reste non teste, signale
explicitement par `studio-tester` : l'entrypoint `studio-client-daemon` en
conditions process reelles (signal natif sur un vrai processus Windows) —
seuls `install_signal_handlers`/`request_stop` sont exerces via les tests
asyncio unitaires.

### Consequences

Aucun changement de contrat (aucun endpoint/evenement/schema touche) ;
additif du cote `ClientConfig` (deux champs a valeur par defaut).
`packages/studio-client` reste sans dependance a `studio-api` (DEC-0024).

### Preuves

`packages/studio-client/src/studio_client/daemon/{__init__,heartbeat}.py`,
`packages/studio-client/src/studio_client/config.py` (deux champs),
`packages/studio-client/pyproject.toml` (script `studio-client-daemon`),
`tests/client/test_daemon.py` (6 tests apres la correction ci-dessus :
`machine_id` manquant rejete, intervalle non-positif rejete, un
intervalle/jitter fixes avec `random_fn` deterministe verifie le calcul
exact du delai, un cycle de trois heartbeats verifie par un `sleep` factice
comptant les appels sans jamais attendre reellement, un `request_stop()`
pendant l'attente qui rend la main promptement au lieu d'epuiser
l'intervalle, et un heartbeat lent — `httpx.MockTransport` bloque sur un
`asyncio.Event` — confirme non abandonne quand `request_stop()` survient
pendant l'appel). Suite `tests/client/` complete rejouee le 2026-09-13 :
48/48 verts (42 existants + 6 nouveaux). `ruff check .`,
`ruff format --check .` (196 fichiers) et `mypy packages/studio-contracts/src
packages/studio-client/src services/api/src services/mcp/src` (strict) verts
(87 fichiers). Suite complete du depot rejouee une premiere fois contre le
seul Postgres 16 local (MinIO pas encore demarre pour ce changement qui ne
touche ni transferts ni stockage) : 153 passed, 11 failed, les 11 echecs
concentres sur `tests/api/test_transfers_storage.py`/`test_transfers_expiration.py`
(`botocore.exceptions.EndpointConnectionError` vers `localhost:9000`) —
diagnostique confirme comme une simple absence de service local, pas un
defaut de ce changement. MinIO local redemarre (meme binaire compile source
que DEC-0013, `go install github.com/minio/minio@latest`, identifiants
`studio`/`studio-dev-secret`, bucket `studio-transfers` recree via boto3)
puis suite complete rejouee : 164 passed, puis une derniere fois apres le
correctif `_wait()` de la revue `studio-tester` : **165 passed**, aucun
echec.
