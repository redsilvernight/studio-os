# P00 - Spike : réaction du daemon à LIBRARY_VERSION_ACTIVATED

Lecture seule, chemins relatifs à la racine du worktree. Les numéros de ligne viennent de lectures partielles ; ce que je n'ai pas lu est marqué « non vérifié ».

## 1. Émission côté API et payload

- Type déclaré : `LIBRARY_VERSION_ACTIVATED = "library.version.activated"` (`packages/studio-contracts/src/studio_contracts/events.py:45`). Voisins : `library.version.created` (:44), `library.resource.deprecated` (:46), `library.lock.set` / `library.lock.released` (:47-48).
- Seul point d'émission : `activate_resource_version` (`services/api/src/studio_api/services/library.py:538-569`). L'événement part après `commit` + `refresh` (:559-568).
- Émission conditionnelle : seulement si `resource.active_version != version or resource.status != "active"` (:555). Réactiver la version déjà active est un no-op sans événement.
- `_emit_library_event` (`library.py:328-368`) retourne sans rien émettre si `resource.project_id is None` (:345). **Les ressources de scope Studio ou User n'émettent donc aucun événement** (commentaire :336-340).
- Payload (`library.py:360-367`) : `{resource_id, kind, stable_key, scope, ref: "v<N>", version: N}`. `ref` vaut `f"v{version}"` (:566).
- Enveloppe (`library.py:347-359`) :
  - `event_id` = uuid5 de `resource.id:event_type:ref` (:350-352).
  - `project_id` = celui de la ressource ; `task_id=None`.
  - `actor_type="user"`, `actor_id=principal.user.id`, `machine_id=principal.machine.id`.
- Piège levé (P20) : `create_event` et `stage_event` renvoient la ligne existante quand l'`event_id` existe déjà. Activer v2, v1 puis v2 réémettait donc le même `event_id` sans nouvel événement (idem pour une dépréciation répétée). Correctif : `_emit_library_event` reçoit `occurrence=resource.version` (compteur incrémenté à chaque transition) pour `library.version.activated` et `library.resource.deprecated`. Test : `test_reactivating_a_version_emits_a_new_event`.
- Le payload ne contient ni `content_hash`, ni dépendances, ni liste des harnais concernés.

## 2. Canaux de réception existants

### 2a. Polling REST `GET /api/v1/events`

- Route décrite comme « the polling and catch-up channel », filtres `project`, `task`, `since` (`services/api/src/studio_api/routers/events.py:76-98` ; texte repris dans `dashboard/src/openapi-schema.ts:1781`).
- Client Python : `StudioApiClient.list_events(project_id, task_id, since, limit=100)` (`packages/studio-client/src/studio_client/api_client.py:502-518`).
- Aucun appelant périodique trouvé côté daemon. Le seul appelant lu est le composeur de contexte, ponctuel, sans `since` (`packages/studio-client/src/studio_client/context/composer.py:292-296`). Grep de `LIBRARY_|library\.` dans `packages/studio-client/src` : aucune consommation de `library.version.*` (grep tronqué à 30 résultats, tous hors sujet).

### 2b. SSE `GET /api/v1/events/stream?project=<uuid>`

- Route : `routers/events.py:105-231`. Le paramètre `project` est obligatoire, **il n'existe pas de flux global** (:147 ; :110).
- Reprise : header `Last-Event-ID` ou `since_seq` (:149-165). Sans curseur, seuls les événements live sont envoyés.
- Keep-alive toutes les 10 s (`services/api/src/studio_api/services/event_stream.py:17`, :196). Revalidation d'accès à chaque item (`events.py:22`, :203-216). Le flux se ferme si l'accès est perdu (:199).
- La distribution passe par `event_stream.subscribe()` (`events.py:174`), une file en mémoire. Fonctionnement avec plusieurs workers ou réplicas API : **non vérifié** (je n'ai pas lu `event_stream.py` en entier).
- Consommateur unique : le dashboard (`dashboard/src/sse.ts:4-19`, `dashboard/src/realtime.ts:13,75`). Il utilise `fetch` + `ReadableStream` car `EventSource` ne gère pas le header Bearer. `realtime.ts:79` ne traite que `resource.conflict` dans le fragment lu ; les autres types sont **non vérifiés**. Aucun consommateur côté `packages/studio-client` (grep `EventSource|stream_events|/stream` : zéro résultat).

### 2c. Websocket

- Aucune occurrence dans `services/api/src`, `dashboard/src/*.ts` ni `packages/studio-client/src` (grep insensible à la casse sur `websocket`, zéro résultat).

### 2d. `studio_sync` (MCP)

- Les règles du projet décrivent `studio_sync` comme canal de coordination entre sessions. Je n'ai pas lu son implémentation ni vérifié s'il relaie des événements `library.*` : **non vérifié**.

### 2e. Ce que fait le daemon de la Library aujourd'hui

- La synchro auto ne se lance qu'**une fois**, au démarrage du daemon : `runtime.py:548-554` appelle `start_auto_sync`. Le runner lance un thread qui fait fetch des projections, planification, application (`skills_bridge.py:1174-1233`, :1347-1356). Il n'y a pas de boucle ; je n'ai pas lu la fin de `_run` (:1255-1344), qui ne semble pas reboucler.
- Autre déclencheur : activer l'option `auto_sync` (`configure_skills`, `skills_bridge.py:1145-1170`, appelle `start_auto_sync` à :1166). `_started` empêche un second démarrage du même runner (:1195-1197).
- Conflits : si des fichiers sont modifiés localement, la synchro saute et passe en état `CONFLICTS` (`skills_bridge.py:1245-1253`).
- Pas de polling serveur-vers-daemon. Les polls périodiques du daemon sont sans rapport avec la Library :
  - heartbeat 30 s avec jitter (`config.py:82`, `heartbeat.py:56-91`) ;
  - lancements de tâches 30 s (`config.py:101`) ;
  - watchers git 30 s, godot 10 s, vault 30 s, scan d'usage 120 s (`config.py:113,118,135`, `local_features.py:277`).
- Le heartbeat appelle `launch_puller.poll()` (`heartbeat.py:110`). Ce mécanisme est piloté par le serveur (task launches) et pourrait servir de modèle, mais il ne transporte pas d'événements Library.

### 2f. Polling de `skills.status` (dashboard)

- `dashboard/src/skillsSync.ts:26-27,341` : appel de `skills.status` toutes les 3 s si l'état est `in_progress`, sinon toutes les 60 s.
- **Ce polling est local** : il lit le fichier de statut du daemon via la commande locale `skills.status` (`dashboard/src/skillsApi.ts:49` ; `skills_bridge.py:1099`). Il ne contacte pas l'API et ne détecte pas qu'une nouvelle version a été activée côté serveur. Il ne fait que refléter l'état que le daemon a écrit.
- Coût : 0 requête réseau vers l'API. Environ 1 appel local/min au repos, 20/min pendant une synchro.

### Fréquence et coût comparés

| Canal | Fréquence | Requêtes par client | Remarque |
|---|---|---|---|
| `GET /events?since=` (à créer côté daemon) | au choix du client | 60 / intervalle en s | exemple : 30 s = 2 req/min, 60 s = 1 req/min ; un `GET` par projet suivi |
| SSE `/events/stream` | connexion unique | ~0 req/min, 1 connexion longue par projet, keep-alive 10 s (~6 frames/min) | reconnexion avec `Last-Event-ID` ; en multi-projet, N connexions |
| `skills.status` | 1/min au repos | 0 vers l'API | local uniquement |
| Heartbeat | 2/min (30 s) | déjà payé | pas de données Library |

## 3. Ce qui manque

1. Aucun consommateur de `library.version.activated` dans le daemon : ni polling `list_events`, ni client SSE Python. Le SSE n'existe que dans le dashboard TypeScript.
2. Pas de boucle de resynchronisation : la synchro auto s'exécute au démarrage ou à l'activation du réglage, jamais ensuite (`runtime.py:549`).
3. Pas de curseur persistant côté daemon (dernier `seq` ou timestamp vu pour `library.*`). Je n'ai pas cherché de table `sync_state` dédiée : **non vérifié**.
4. Les ressources de scope Studio et User n'émettent aucun événement (`library.py:345`). Un déclencheur sur événement ne couvre que les ressources de projet. Les ressources Studio, sans `project_id`, exigent un autre signal (sondage de la liste des projections).
5. Pas de flux global : un client suivant plusieurs projets a besoin d'un flux par projet (`events.py:147`).
6. Le payload ne porte ni hash ni liste de harnais ; le daemon devra refaire un `fetch_library_projections` complet (`skills_bridge.py:257`, :663) pour planifier. Il n'existe pas de fetch ciblé par ressource, **non vérifié**.
7. Déduplication possible des réactivations (voir § 1, **non vérifié**).
8. Garde-fous à définir : conflits locaux (la synchro saute, `skills_bridge.py:1245`), autorisation d'écriture sur le disque sans confirmation de l'utilisateur (la synchro auto applique déjà sans confirmation, `skills_bridge.py:1174-1233`).

## 4. Recommandation pour P20 (déclencheur de synchro auto)

Recommandation : **poll périodique de `GET /events?since=&project=` dans le daemon, filtré sur les `event_type` `library.version.activated` (et `library.resource.deprecated`), qui déclenche un `_AutoSyncRunner` rejouable. Garder une resynchro complète à intervalle long comme filet de sécurité.**

Raisons :
- Le canal polling est documenté comme canal de rattrapage (`routers/events.py:76-98`) et le client Python existe déjà (`api_client.py:502-518`).
- Le daemon suit déjà le schéma « boucle à intervalle + jitter + arrêt propre » : `watchers/base.py:14-48`, `heartbeat.py`. Un nouveau watcher peut en hériter sans nouvelle infrastructure.
- Coût borné : 2 req/min par client et par projet avec un intervalle de 30 s (cohérent avec `config.py:101,113`). Alignement possible sur le heartbeat pour ne pas ajouter de timer.
- Écrire un client SSE Python avec header Bearer, reprise `Last-Event-ID` et backoff coûte plus cher. De plus, le fonctionnement de `event_stream` en multi-process n'est pas vérifié (§ 2b). SSE pourrait venir ensuite comme optimisation de latence si 30 s est trop lent.
- Aucune dépendance au websocket, qui n'existe pas.

Implémentation minimale proposée :
1. Watcher `LibraryEventWatcher(PollingWatcher)` : `poll_once` appelle `list_events(project_id=…, since=curseur)` pour les projets suivis ; si au moins un événement `library.version.activated` ou `library.resource.deprecated` est vu, il relance la synchro auto.
2. Rendre le runner rejouable : aujourd'hui `_started` bloque tout second lancement (`skills_bridge.py:1195-1197`). Ajouter une méthode de relance en gardant un seul thread actif à la fois (coalescer les événements pendant une synchro).
3. Persister le curseur (timestamp serveur de l'événement) dans le répertoire de données du daemon. Après un redémarrage, la synchro au démarrage (`runtime.py:549`) couvre le trou ; le curseur sert au reste.
4. Pour les ressources Studio/User : prévoir un resync complet périodique (par exemple 10 à 15 min), ou ajouter une émission côté API sans `project_id`. Ce second choix change le contrat d'événements (`events` exige un `project_id` non nul, `library.py:336-340`), donc passe par le skill `contract-change`.
5. Doute sur l'`event_id` déterministe tranché et corrigé (§ 1).
6. Garder le comportement `CONFLICTS` (pas d'écrasement local, `skills_bridge.py:1245-1253`).

Risques résiduels : latence jusqu'à 30 s ; N requêtes par client pour N projets suivis ; événements Studio/User non couverts tant que le point 4 n'est pas traité.

## Non vérifié (récapitulatif)

`event_stream.py` hors constante :17 (comportement multi-worker) ; `studio_sync` et `studio_get_recent_changes` comme canal de `library.*` ; traitement des autres `event_type` dans `dashboard/src/realtime.ts` ; fin de `_AutoSyncRunner._run` (:1255-1344) ; existence d'un curseur persistant côté daemon ; existence d'un fetch ciblé par ressource.
