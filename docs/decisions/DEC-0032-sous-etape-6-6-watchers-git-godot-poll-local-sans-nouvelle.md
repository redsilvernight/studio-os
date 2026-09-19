---
id: DEC-0032
title: 'Sous-etape 6.6 (watchers Git/Godot) : poll local sans nouvelle dependance,
  PR hors perimetre'
status: active
date: '2026-09-14'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:690d5ca7422f2ac67a93c0a93f1aa3f428aaf8ccbce0e3c934d018c383ecb43d
graphify_entities:
- kind: class
  node_id: packages_studio_client_src_studio_client_watchers_base_pollingwatcher
  path: packages/studio-client/src/studio_client/watchers/base.py
  project: studio-os
  relation: implements
  symbol: PollingWatcher
- kind: class
  node_id: packages_studio_client_src_studio_client_watchers_git_watcher_gitwatcher
  path: packages/studio-client/src/studio_client/watchers/git_watcher.py
  project: studio-os
  relation: implements
  symbol: GitWatcher
- kind: class
  node_id: packages_studio_client_src_studio_client_watchers_godot_watcher_godotwatcher
  path: packages/studio-client/src/studio_client/watchers/godot_watcher.py
  project: studio-os
  relation: implements
  symbol: GodotWatcher
- kind: function
  node_id: packages_studio_client_src_studio_client_daemon_heartbeat_build_watchers
  path: packages/studio-client/src/studio_client/daemon/heartbeat.py
  project: studio-os
  relation: implements
  symbol: build_watchers
---

# DEC-0032 — Sous-etape 6.6 (watchers Git/Godot) : poll local sans nouvelle dependance, PR hors perimetre

Etudie sans `studio-architect` (meme principe que 6.2-6.5 : consomme
`EventType`/`EventCreate` et l'outbox deja contractualises, aucune
frontiere de contrat nouvelle).

### Probleme

Rien ne detectait localement un commit, un changement de branche ou le
demarrage/arret de Godot pour les faire remonter au serveur — les
evenements `git.*`/`godot.*` existent dans `TECH/03_EVENT_CONTRACT.md`
depuis le debut mais rien ne les emettait cote client.

### Decision

- `studio_client/watchers/base.py` : `PollingWatcher`, boucle poll/stop
  partagee entre les deux watchers, calquee sur
  `HeartbeatDaemon._wait`/`request_stop` (sous-etape 6.2, DEC-0028) —
  `request_stop()` ne coupe jamais un `poll_once()` en vol, `_wait`
  rend la main des que l'arret est demande. Un `poll_once()` qui leve
  est journalise et saute (le prochain poll reessaiera), jamais fatal
  a la boucle — meme tolerance offline que le reste du client
  (`.claude/rules/offline-sync.md`).
- `GitWatcher` (`git_watcher.py`) : lit `HEAD`/la branche via `git
  rev-parse` (sous-processus, jamais de bibliotheque Git). Le premier
  poll n'etablit qu'une base (`sync_state`, cle
  `git_watcher:<repo_path>`) sans emettre — seules les transitions
  observees ensuite produisent `git.branch.changed` puis `git.commit`
  (dans cet ordre si les deux changent dans le meme poll). Un poll
  illisible (`git` absent, pas encore un depot) rend `None` et ne
  touche pas l'etat stocke plutot que de lever a chaque intervalle.
  **`git.pr.opened`/`git.pr.merged` ne sont pas emis** : une PR
  n'existe que sur GitHub/un remote, et aucun client GitHub n'existe
  encore dans le Bloc B (`IMPLEMENTATION/03_BLOCK_B_PROMPT.md` le liste
  comme une responsabilite future separee des watchers) — rien a
  interroger localement pour ces deux types. Ecart documente ici,
  pas silencieux.
- `GodotWatcher` (`godot_watcher.py`) : detecte un processus dont le
  nom contient un motif configurable (`godot` par defaut) via
  `tasklist` (Windows) ou `ps -A` (POSIX) en sous-processus — **pas de
  nouvelle dependance** (`psutil` aurait ete la voie naturelle mais
  `packages/studio-client` est limite a
  `studio-contracts`/`httpx`/`pydantic-settings`/`keyring`, DEC-0024).
  Meme regle de base sans emission au premier poll : un processus deja
  lance avant le demarrage du watcher ne produit jamais un
  `godot.started` retroactif, seules les transitions reellement
  observees comptent.
- `ClientConfig` : quatre champs additifs, tous optionnels
  (`git_watch_repo_path`/`git_watch_project_id`/
  `godot_watch_process_pattern`/`godot_watch_project_id` + les deux
  `*_interval_seconds`) — un watcher ne demarre que si son champ propre
  ET son `*_project_id` sont tous deux renseignes, jamais l'un sans
  l'autre. `daemon/heartbeat.py:build_watchers()` construit la liste
  effective ; `main()` les fait tourner en parallele du heartbeat
  (`asyncio.gather`) et propage `request_stop()` a tous sur
  SIGINT/SIGTERM.
- `actor_type="system"`/`actor_id=machine_id` pour les evenements emis
  par un watcher — aucun acteur humain/agent n'est a l'origine d'un
  commit ou d'un lancement Godot detectes passivement ; c'est la
  machine elle-meme qui rapporte un fait observe.
- L'enqueue de l'evenement et la mise a jour de `sync_state` partagent
  la meme transaction SQLite (`transaction()`) : un crash entre les
  deux ne perd rien (rien n'est commite) plutot que de risquer un
  evenement commite sans son marqueur de dedoublonnage (qui produirait
  un re-emission a chaque poll suivant).

### Consequences

Aucun changement de contrat (les quatre `EventType` git/godot
existaient deja) ni de nouvelle dependance. Ecart residuel assume :
`git.pr.opened`/`git.pr.merged` restent non emis jusqu'a l'existence
d'un client GitHub (item distinct de `03_BLOCK_B_PROMPT.md`, hors
perimetre watchers). Cible Windows uniquement testee en reel pour les
deux lecteurs par defaut (postes clients Windows par invariant projet,
`docs/Studio_OS_Documentation_Pack/.../CURRENT.md`) ; le lecteur POSIX
de `GodotWatcher` (`ps -A`) n'a pas de machine Linux/macOS disponible
pour verification reelle dans cette session — code au meme niveau de
simplicite que la branche Windows, a verifier reellement si un poste
client non-Windows existe un jour.

### Preuves

`packages/studio-client/src/studio_client/watchers/{base,git_watcher,
godot_watcher}.py`, `config.py` (+4 champs), `daemon/heartbeat.py`
(`build_watchers`, wiring `main()`). `tests/client/test_watchers.py`
(11 tests : baseline sans emission, commit seul, branche seule, les
deux dans l'ordre branche-puis-commit, lecture illisible, arret rapide
de la boucle pour Git, meme matrice pour Godot (baseline/demarrage/
arret/aucune transition), tolerance a une exception de poll). Suite
complete du depot : **216 passed** (Postgres 16 + MinIO reels,
conteneurs locaux temporaires). `ruff check .`, `ruff format --check .` et
`mypy packages/studio-contracts/src packages/studio-client/src
services/api/src services/mcp/src` (strict, commande CI reelle) verts.
Verification manuelle hors mock : `default_git_reader(Path('.'))`
contre le depot reel (retourne le HEAD/branche reels) ;
`default_process_probe('python')` -> `True` sur ce poste (interprete
en cours), `default_process_probe('definitely-not-a-real-process')`
-> `False`. `build_watchers()` verifie construisant bien 0 watcher sans
config et 2 avec, contre un `OutboxStore` reel.

Validation independante `studio-tester` (conteneurs Postgres/MinIO
propres, meme methode) : chiffres reconfirmes a l'identique (216
passed, ruff/format/mypy verts), aucun bug bloquant sur la logique de
transaction (`enqueue_event`+`set_sync_state` atomiques, un rollback ne
laisse ni ligne orpheline ni doublon — le poll suivant recalcule le
meme diff et regenere un `event_id` frais) ni sur la parite
`PollingWatcher`/`HeartbeatDaemon`. Deux limites non bloquantes
relevees et corrigees/consignees ici :
- Le nombre de tests annonce (14) etait faux (11 reels) — corrige
  ci-dessus ; le test verifiant l'ordre branche-puis-commit utilisait
  `sorted(...)` et ne prouvait donc pas l'ordre revendique — corrige
  pour comparer une liste ordonnee (`tests/client/test_watchers.py`,
  desormais verifie reellement en plus d'etre implemente correctement).
- `main()._run()` : `asyncio.gather(daemon.run(), *watchers)` sans
  `return_exceptions=True` ni annulation croisee — si `daemon.run()`
  leve une exception non geree pendant qu'un watcher tourne encore,
  `gather` remonte l'exception mais le(s) watcher(s) restent des
  taches actives non annulees (avertissement asyncio possible a la
  fermeture de la boucle). N'affecte aucun chemin nominal (le
  heartbeat catche deja `StudioApiError` en interne) ; a garder en tete
  si un futur correctif touche l'arret du daemon, hors perimetre de
  cette sous-etape pour le traiter maintenant.

## Addendum — surveillance multi-depots (un daemon, N `GitWatcher`)

Etendu ici plutot que par une nouvelle DEC : meme perimetre (watchers
Git), aucune frontiere de contrat nouvelle. Audit prealable : `/events`
et la table `events` portent deja `project_id` par evenement sans le lier
a la machine ; l'outbox et `sync_state` sont communs ; `asyncio.gather`
de `main()` fait deja tourner N watchers. Aucun changement backend,
contrat, evenement ni Dashboard.

### Decision

Un daemon par machine surveille plusieurs depots Git, chacun associe a
son projet Studio OS ; les evenements `git.commit` / `git.branch.changed`
partent avec le `project_id` du depot qui les a detectes.

```text
1 daemon -> N GitWatcher (depot A/projet A, depot B/projet B, ...) -> 1 Outbox -> API
```

- Format canonique (TOML, `ClientConfig.git_watches`,
  `studio_client.config.GitWatchConfig`) :

  ```toml
  [[git_watches]]
  repo_path = "C:/Dev/studio-os"
  project_id = "UUID_A"

  [[git_watches]]
  repo_path = "C:/Dev/BLFinder"
  project_id = "UUID_B"
  ```

  Via l'environnement : `STUDIO_CLIENT_GIT_WATCHES` (tableau JSON).
  `git_watch_interval_seconds` reste global et partage.
- Format legacy `git_watch_repo_path` + `git_watch_project_id`
  (TOML ou `STUDIO_CLIENT_GIT_WATCH_*`) toujours accepte : normalise au
  chargement en une liste d'un element ; ensuite le programme ne voit que
  `git_watches` (les deux champs legacy valent `None` apres chargement).
- Validation fail-closed a la construction de `ClientConfig` : une entree
  sans `repo_path` ou sans `project_id` est rejetee ; un seul des deux
  champs legacy est rejete (avant, le watcher restait silencieusement
  desactive) ; ancien ET nouveau format simultanement sont rejetes, sans
  fusion implicite ; un depot en double est rejete meme avec un autre
  `project_id` (chemin absolu normalise, insensible a la casse sous
  Windows). Un meme `project_id` pour plusieurs depots reste permis
  (front/back d'un meme projet).
- Aucune entree Git -> aucun `GitWatcher`, le daemon tourne normalement.
  Un depot temporairement illisible/absent reste tolere (poll saute, cf.
  ci-dessus) : seule la structure de la config est validee.
- Identite persistee inchangee : `sync_state` cle
  `git_watcher:<repo_path absolu>`, donc HEAD/branche de chaque depot ont
  leur propre baseline et un depot n'est jamais compare a un autre. Les
  baselines des installations existantes (chemin deja absolu) sont
  conservees.
- `ContextComposer` (source `git`) resout le depot par `project_id` via
  `ClientConfig.git_repo_for_project` (premier depot declare pour ce
  projet) au lieu de l'ancien `git_watch_repo_path` unique : un Context
  Package n'embarque plus l'historique d'un depot appartenant a un autre
  projet.

### Consequences

Changement de comportement assume : un ancien `git_watch_repo_path` seul
(sans `git_watch_project_id`), qui alimentait le seul snapshot Git du
Context Package, est maintenant rejete au chargement avec un message
explicite. Hors perimetre, inchange : statut du working tree, staging,
push, PR GitHub, association commit/tache.

### Preuves

`tests/client/test_config.py` (normalisation legacy, rejets, doublons,
chemins relatifs/casse), `tests/client/test_watchers.py` (`build_watchers`
0/1/3 depots ; deux depots Git reels temporaires : commit A seul -> un
`git.commit` projet A, aucun pour B ; branche ; reconstruction des
watchers sans faux evenement ; deux watchers sur une meme outbox).
