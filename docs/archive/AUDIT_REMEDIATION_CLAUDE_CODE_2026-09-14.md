# Audit d'avancement et brief de remédiation pour Claude Code

Date : 2026-09-14

> **Archivé le 2026-09-15 — tous les défauts ci-dessous sont corrigés dans le
> code actuel** (vérifié par lecture directe : `services/mcp/src/studio_mcp/auth.py`,
> `packages/studio-client/src/studio_client/outbox/replay.py`,
> `services/api/src/studio_api/services/events.py`, `ensure_can_write`/
> `require_roles` sur les routers, `packages/studio-client/src/studio_client/transfers.py`).
> Conservé pour l'historique ; ne pas relancer ce travail. Pour l'état courant,
> se référer à `docs/DECISIONS.md` et `docs/ROADMAP_CORRECTIONS_AUDIT.md`.

## Mandat

Corriger les défauts ci-dessous dans l'ordre indiqué, en partant de l'état réel
du dépôt. Le périmètre est strictement limité aux étapes déjà commencées de
`docs/ROADMAP_CORRECTIONS_AUDIT.md` : étapes 1 à 6 closes et étape 7 en cours.
Ne pas démarrer les étapes 8 (connaissance IA), 9 (producer/media/hardening
final) ou 10 (réconciliation documentaire générale).

Avant toute modification :

1. vérifier `git status`, les changements utilisateur et l'état des tests ;
2. lire `docs/DECISIONS.md` et les contrats concernés ;
3. conserver le fichier utilisateur non suivi
   `.claude/settings.json.graphify-bak` sans le modifier ni le supprimer ;
4. utiliser `studio-architect` avant toute décision d'autorisation transverse ;
5. utiliser `contract-change` et `contract-guardian` pour tout changement
   observable des contrats API, Event ou Auth/Sync ;
6. faire valider chaque lot terminé par `studio-tester` ;
7. mettre à jour Graphify au point de complétion via
   `pwsh -NoProfile -File scripts/graphify-studio.ps1 update` et consigner le
   coût réel.

## État audité

- Révision : `045afe3` sur `master`.
- Arbre de travail : propre hors
  `.claude/settings.json.graphify-bak` non suivi.
- Tests locaux réels : `292 passed in 36.22s`.
- Ruff : `All checks passed!` et `253 files already formatted`.
- mypy strict : `Success: no issues found in 96 source files`.
- Roadmap : étapes 1 à 6 déclarées closes ; étape 7 commencée par DEC-0034.
- Les phases 8 à 10 n'ont pas été auditées et ne font pas partie de ce mandat.

La suite verte ne couvre pas les défauts ci-dessous. Deux d'entre eux ont été
reproduits directement pendant l'audit.

## P0 — Empêcher le repli du token stdio dans une requête MCP HTTP

### Constat

`services/mcp/src/studio_mcp/auth.py::_extract_token` revient toujours à
`STUDIO_MCP_MACHINE_TOKEN` après l'inspection des headers. Ainsi, un contexte
HTTP avec `headers={}` et sans `Authorization` hérite du token de processus si
la variable existe. Cela contredit `TECH/04_AUTH_SYNC_CONTRACT.md`, qui réserve
ce repli au transport stdio, et peut transformer une erreur de configuration du
conteneur en contournement d'authentification.

Reproduction obtenue :

```text
http_context_without_authorization_resolves= dummy-stdio-token
```

### Correction attendue

- Quand un contexte HTTP existe (`ctx.headers is not None`), n'accepter que le
  bearer token de cette requête. L'absence ou la malformation du header doit
  produire `unauthenticated` ; ne jamais consulter la variable d'environnement.
- N'utiliser `STUDIO_MCP_MACHINE_TOKEN` que quand le contexte ne porte aucun
  ensemble de headers, c'est-à-dire le chemin stdio établi par le serveur.
- Ne pas journaliser le token.

### Tests obligatoires

- HTTP sans `Authorization` + variable stdio définie : rejet.
- HTTP avec bearer invalide + variable stdio valide : rejet, sans repli.
- stdio (`headers is None`) + variable valide : succès conservé.
- bearer HTTP valide : succès conservé.

Ce lot aligne le code sur le contrat existant ; ne pas inventer une nouvelle
sémantique de transport.

## P0 — Rendre persistants les résultats du replay outbox

### Constat

`OutboxReplayer.replay_ready()` appelle `mark_succeeded`, `mark_failed` et
`move_to_dead_letter` sans transaction ni commit. Les méthodes du store sont
volontairement non-committantes. Les tests actuels relisent avec la même
connexion et voient donc les changements non validés, ce qui masque le défaut.

Reproduction obtenue après `mark_succeeded`, avec une seconde connexion SQLite :

```text
visible_from_second_connection_after_mark_succeeded= 1
```

Après un crash ou redémarrage, une ligne déjà envoyée peut donc revenir, le
backoff d'un échec peut être perdu et une dead-letter peut ne pas être durable.
L'idempotence serveur limite les doublons métier, mais ne répare pas la
persistance locale exigée par `TECH/08_OFFLINE_SYNC.md`.

### Correction attendue

- Encadrer chaque transition de replay dans `transaction(store.connection)` :
  succès, échec transitoire et déplacement en dead-letter.
- Garder l'appel réseau hors de la transaction SQLite.
- Une transition et la suppression/écriture qu'elle implique doivent être
  atomiques.
- Ne pas rendre toutes les méthodes du store auto-committantes : leur contrat
  permet à l'appelant de grouper une écriture locale et un enqueue dans une même
  transaction.

### Tests obligatoires

Pour chacun des trois chemins, fermer ou ignorer la connexion productrice puis
ouvrir une seconde connexion au même fichier :

- succès : la ligne pending a disparu durablement ;
- erreur transitoire : `attempt_count`, `next_attempt_at` et `last_error` sont
  durables ;
- erreur définitive : pending supprimé et dead-letter durable dans la même
  transaction ;
- rollback injecté : jamais de demi-transition.

## P1 — Lier l'identité des événements à la machine authentifiée

### Constat

- HTTP : `services/api/src/studio_api/services/events.py` persiste
  `event_in.machine_id`, `actor_type` et `actor_id` fournis par le client sans
  les confronter à `CurrentMachine`.
- MCP : `studio_emit_event` accepte un `machine_id` arbitraire et ne remplace
  celui-ci par `machine.id` que lorsque le paramètre est omis.
- Heartbeat : le serveur met correctement à jour la machine authentifiée, mais
  ignore silencieusement un `HeartbeatRequest.machine_id` contradictoire.

Un token machine valide peut donc attribuer un événement à une autre machine.
Cela nuit directement à la traçabilité AIWorkLog/Event, invariant du projet, et
contredit la règle Auth/Sync selon laquelle un outil MCP écrivain dérive son
`machine_id` de l'identité authentifiée.

### Correction attendue

- Dériver systématiquement `machine_id` de `CurrentMachine` pour les écritures
  HTTP et MCP, ou rejeter explicitement une valeur fournie différente.
- Définir et documenter la règle de validation de `actor_type`/`actor_id`
  (machine, user propriétaire ou agent rattaché). Ne pas choisir cette matrice
  implicitement dans le code.
- Pour heartbeat, rejeter un identifiant de corps différent avec une erreur
  machine-readable, ou supprimer ce champ lors d'une version de contrat
  explicitement gérée. Ne pas continuer à l'ignorer silencieusement.
- Préserver l'idempotence par `event_id` : un replay ne doit ni changer
  l'identité enregistrée ni produire un doublon.

### Processus contractuel

Ce lot touche `TECH/03_EVENT_CONTRACT.md` et
`TECH/04_AUTH_SYNC_CONTRACT.md`. Lire les sections courantes, classifier le
changement, mettre à jour contrats, fixtures et mocks dans le même lot, créer
une DEC si la matrice d'identité tranche une ambiguïté, puis faire intervenir
`contract-guardian`.

### Tests obligatoires

- HTTP et MCP : tentative de `machine_id` différent rejetée ou normalisée selon
  la décision, avec assertion sur la ligne DB réelle.
- Rejeu du même `event_id` avec identité contradictoire : aucune altération de
  l'événement original.
- Agent inconnu ou non rattaché : comportement explicite couvert.
- Heartbeat avec `req.machine_id != authenticated_machine.id` couvert.

## P1 — Définir puis appliquer une autorisation transverse minimale

### Constat

Le dépôt reconnaît les rôles `admin|developer|agent|readonly`, mais
`require_roles` n'est appliqué qu'au provisioning. Le déficit est déjà admis
dans `docs/ROADMAP_STEP4_BREAKDOWN.md` : aucune ACL projet/rôle sur le reste de
l'API. Concrètement, toute machine authentifiée peut notamment lister tous les
transferts, obtenir une URL de téléchargement et supprimer un transfert dont
elle n'est ni émettrice ni destinataire. Le même défaut touche projets, tâches,
événements, sessions, claims, décisions et AI Work Ledger.

### Travail attendu

Ne pas ajouter des contrôles endpoint par endpoint sans modèle partagé.

1. Faire produire par `studio-architect` une matrice minimale de lecture et
   écriture compatible avec les deux développeurs distants et le rôle
   `readonly`.
2. Décider si une ACL projet nécessite un modèle d'appartenance. Toute nouvelle
   table ou relation exige contrat Data Model et migration réversible.
3. Appliquer la même politique aux couches HTTP et MCP via des services
   communs ; ne pas dupliquer la logique dans les handlers.
4. Pour Transfer, couvrir au minimum émetteur, destinataire et admin pour
   métadonnées, URL signée et suppression.
5. Retourner des erreurs machine-readable sans révéler l'existence d'une
   ressource interdite si la politique retient un 404 de confidentialité.

### Tests obligatoires

- Matrice par rôle, sur au moins deux utilisateurs et deux machines.
- Accès inter-projet et accès à un transfert tiers.
- Parité HTTP/MCP.
- Révocation immédiate d'un token conservée.
- Aucun octet fichier ne traverse FastAPI ou MCP.

Ce lot est un changement architectural et contractuel : `studio-architect`,
`contract-change`, DEC, migration éventuelle et `contract-guardian` sont
obligatoires avant clôture.

## P2 — Fermer les limites de reprise et d'intégrité de TransferClient

### 1. Reprise multipart après expiration des URLs

DEC-0033 assume qu'un upload interrompu plus longtemps que le TTL ne peut pas
reprendre : le client réutilise indéfiniment les URLs expirées. Cela réduit la
garantie offline et empêche une vraie reprise longue après redémarrage.

- Concevoir un mécanisme additif permettant de re-présigner les parts manquantes
  pour le même `upload_id`, sans réenvoyer les parts terminées et sans faire
  transiter de bytes par l'API.
- Valider que l'`upload_id` reste lié à l'`object_key` du Transfer et que le
  demandeur est autorisé.
- Prévoir l'abandon/nettoyage des uploads multipart définitivement orphelins.
- Ce changement exige contrat API, mocks Bloc B, DEC et `contract-guardian`.

Test d'acceptation : interrompre après environ 50 %, dépasser réellement le TTL,
redémarrer le client avec la même SQLite, rafraîchir les URLs, n'envoyer que les
parts manquantes et vérifier le fichier final octet à octet.

### 2. Fichier local de téléchargement déjà trop grand ou corrompu

`TransferClient.download()` retourne immédiatement dès que
`existing_bytes >= transfer.size_bytes`. Un fichier plus grand que prévu est
donc accepté comme complet. DEC-0033 admet aussi qu'un fichier de bonne taille
mais de contenu différent est accepté.

- Retourner une `TransferError` si la taille locale dépasse la taille attendue.
- Après un téléchargement ou un no-op de taille exacte, vérifier le SHA-256
  lorsque `transfer.sha256` est présent. Préciser qu'il s'agit d'une comparaison
  au hash déclaré par l'émetteur, pas d'une vérification serveur du multipart.
- Ne pas détruire silencieusement un fichier existant incorrect ; laisser au
  caller une option explicite de remplacement si nécessaire.

Tests : fichier surdimensionné, même taille/contenu différent, reprise valide,
hash absent, hash valide et hash invalide.

### 3. Paramètre de concurrence invalide

Valider `part_concurrency >= 1` dans le constructeur. Une valeur zéro crée un
sémaphore qui ne se libère jamais et bloque l'upload.

## P2 — Terminer honnêtement l'étape 7 et corriger son suivi local

La roadmap n'a barré que deux scénarios, alors que des preuves existent déjà :

- mauvais Content-MD5 : `tests/api/test_transfers_storage.py` ;
- quota dépassé et concurrence du quota : `tests/api/test_transfers_quota.py` ;
- expiration/suppression : `tests/api/test_transfers_expiration.py` ;
- download Range réel et reprise à 50 % sur 220 MiB : preuve DEC-0033 ;
- URL expirée et claims concurrents : DEC-0034.

Après vérification directe de ces preuves, mettre à jour uniquement la section
de l'étape 7, sans lancer l'étape 10 générale. Ne pas transformer une preuve
mockée en preuve réelle.

Scénarios réellement encore ouverts dans l'étape commencée :

1. multipart 1 Go réel ;
2. reprise longue après expiration des URLs (après le correctif ci-dessus) ;
3. deux machines simulées sur des réseaux/clients distincts ;
4. replay offline bout-en-bout avec au minimum Task, Event et AIWorkLog, coupure,
   redémarrage du daemon, reconnexion, ordre et absence de doublon ;
5. consigner pour chaque test manuel éventuel environnement, commande, date et
   résultat reproductible.

Éviter d'allouer plusieurs gigaoctets en mémoire : générer/streamer le corpus de
test, borner la concurrence et nettoyer les objets/conteneurs dans un `finally`.

## Validation finale exigée

Exécuter au minimum :

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/studio-contracts/src packages/studio-client/src services/api/src services/mcp/src
git diff --check
```

Ajouter les validations ciblées réelles PostgreSQL/MinIO nécessaires à chaque
lot. Ne pas affirmer qu'un test VPS, TLS, deux réseaux physiques ou GitHub
Actions a été réalisé sans preuve réelle.

À la fin, produire un compte rendu contenant : fichiers modifiés, migrations,
contrats/DEC, tests et sorties exactes, limites restantes, validation
`studio-tester`, verdict `contract-guardian` le cas échéant, et coût de la mise à
jour Graphify.
