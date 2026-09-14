# Roadmap de correction — audit Studio OS

Date de l'audit : 2026-09-13

Cette roadmap transforme les constats de l'audit du dépôt en étapes de travail
ordonnées. Elle complète la roadmap produit normative située dans
`Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/01_ROADMAP.md` sans
la remplacer.

## Principes d'exécution

- Traiter en premier les défauts qui compromettent la cohérence des données sous
  concurrence.
- Ne modifier aucun contrat API, Event, Auth/Sync ou Data Model silencieusement.
- Ajouter les tests de régression avant ou avec chaque correction.
- Dispatcher `contract-guardian` si une correction modifie un comportement
  contractuel observable.
- Dispatcher `studio-tester` après chaque feature ou correction terminée.
- Mettre à jour Graphify au point de complétion de chaque étape.

## Étape 1 — Sécuriser l'idempotence sous concurrence (P1) — CLOS

Réservation Postgres atomique (`INSERT ... ON CONFLICT DO NOTHING` avant la
création métier) + `_reclaim_if_abandoned` pour une réservation `pending`
abandonnée + `request_hash` désormais vérifié (409
`idempotency_key_payload_mismatch` sur un replay à payload différent) :
`docs/DECISIONS.md` DEC-0015. Régression couverte par
`tests/api/test_idempotency_concurrency.py` (dix requêtes concurrentes
réelles, une seule `Task` créée).

### Problème

`run_idempotent` crée et valide actuellement la ressource métier avant de
réserver la paire `(Idempotency-Key, endpoint)`. Deux requêtes concurrentes
peuvent donc créer deux ressources, même si une seule ligne d'idempotence finit
par survivre.

Le champ `request_hash` est stocké mais n'est pas contrôlé lors d'un replay.
Il faut décider, à partir des contrats et décisions existants, si une même clé
réutilisée avec un payload différent doit rejouer la première réponse ou
retourner une erreur explicite. Tout changement observable doit suivre le
processus de changement de contrat.

### Travail attendu

1. Écrire un test de concurrence déterministe reproduisant le doublon.
2. Choisir une stratégie transactionnelle atomique compatible avec PostgreSQL
   (réservation de clé, verrouillage ou transaction unique).
3. Garantir qu'une seule ressource métier est créée pour une même clé et un même
   endpoint.
4. Couvrir au minimum tasks, claims, decisions, transfers, sessions, ai-work et
   projects.
5. Tester le replay après commit, la concurrence et l'échec de la création
   métier.
6. Documenter la sémantique du `request_hash` et appliquer `contract-change` si
   elle change le comportement public.

### Critères d'acceptation

- Deux créations simultanées avec la même clé produisent un seul objet métier.
- Les deux réponses désignent exactement cet objet.
- Une création échouée ne laisse pas une clé bloquée ou une réponse fantôme.
- Les tests existants restent verts.
- Ruff et mypy passent sur les fichiers de production modifiés.

## Étape 2 — Rendre les identifiants DEC-XXXX concurrents (P1) — CLOS

Remplacement de `COUNT(*) + 1` par une séquence Postgres dédiée
(`decisions_readable_id_seq`, `nextval()` atomique) : `docs/DECISIONS.md`
DEC-0016. Migration Alembic `0003` réversible. Régression couverte par
`tests/api/test_decisions_concurrency.py` (dix créations concurrentes, dix
`readable_id` distincts).

### Problème

`_next_readable_id` utilise `COUNT(*) + 1`. Deux décisions créées en parallèle
peuvent obtenir le même identifiant lisible ; une suppression future pourrait
aussi provoquer une réutilisation.

### Travail attendu

1. Ajouter un test de créations concurrentes.
2. Remplacer le comptage par un mécanisme PostgreSQL atomique et monotone.
3. Préserver le format public `DEC-XXXX`.
4. Ajouter la migration Alembic réversible nécessaire.
5. Vérifier les conséquences sur les fixtures et contrats partagés.

### Critères d'acceptation

- Chaque décision concurrente reçoit un identifiant unique.
- Les identifiants ne sont jamais réutilisés après suppression.
- La migration monte et redescend proprement sur une base de test.

## Étape 3 — Fermer la dette immédiate de qualité (P2/P3) — CLOS

Deux erreurs mypy `[type-arg]` sur `sa.Column` non paramétré (migration
`0001_initial.py`) corrigées en `sa.Column[Any]` ;
`HTTP_422_UNPROCESSABLE_ENTITY` remplacé par
`HTTP_422_UNPROCESSABLE_CONTENT` (`services/transfers.py`) ; `pytest`/`ruff
check`/`mypy` déjà présents en CI (`.github/workflows/ci.yml`), rien à
ajouter : `docs/DECISIONS.md` DEC-0017. Vérifié : `mypy` sur les 4 racines CI
→ `Success: no issues found` ; suite complète → 42 passed (Postgres + MinIO
réels).

### Travail attendu

1. Corriger les deux erreurs mypy de la migration initiale concernant les types
   génériques `Column`.
2. Remplacer `HTTP_422_UNPROCESSABLE_ENTITY` par la constante Starlette actuelle.
3. Ajouter ces contrôles à la validation continue si ce n'est pas déjà fait :
   `pytest`, `ruff check` et `mypy`.
4. Vérifier que les migrations restent exécutables, pas seulement typables.

### Critères d'acceptation

- `pytest`, Ruff et mypy terminent sans erreur ni avertissement connu lié à ces
  éléments.

## Étape 4 — Terminer le périmètre Cloud/Core du Bloc A (P1/P2) — CLOS

Cinq sous-étapes closes : realtime SSE + curseur `seq` (DEC-0018, 4.1),
quotas/taille max/vue de consommation des transferts (DEC-0019, 4.2), worker
d'expiration `studio-admin transfers expire` (DEC-0020, 4.3), sauvegarde/
restauration Postgres+MinIO par scripts shell (DEC-0021, 4.4), validation
Docker Compose sur base strictement vierge — bootstrap, migrations,
realtime, quotas, expiration, backup/restore rejoués en conditions réelles
(DEC-0022, 4.5). Voir `docs/ROADMAP_STEP4_BREAKDOWN.md` pour le détail par
sous-étape.

### Travail attendu

1. Implémenter le realtime prévu par le cahier des charges et définir clairement
   son transport et son modèle de reprise.
2. Ajouter quotas, limites de taille et vue de consommation pour les transferts.
3. Implémenter le worker d'expiration/nettoyage selon une politique explicite de
   rétention.
4. Documenter et automatiser les sauvegardes PostgreSQL/MinIO.
5. Réaliser et documenter un test complet de restauration.
6. Vérifier le déploiement Docker Compose sur une base vierge, migration comprise.

### Critères d'acceptation

- Les responsabilités du Bloc A listées dans
  `IMPLEMENTATION/02_BLOCK_A_PROMPT.md` sont toutes présentes ou explicitement
  reportées par décision validée.
- Une restauration PostgreSQL et objet est démontrée.
- Les transferts expirés suivent une politique testée et traçable.

## Étape 5 — Étendre le serveur MCP vers le contrat cible (P2) — CLOS

Auth par requête (DEC-0023, pas de token process-wide — le service `mcp` est
multi-client en prod) et 25 des 29 outils cibles implémentés (les 4
mémoire/Graphify/Context Package restent différés, écart documenté dans
`TECH/07_MCP_CONTRACT.md`) : `docs/DECISIONS.md` DEC-0023. 49 tests réels
(Postgres 16 conteneurisé, succès + erreur par outil) + 55 tests existants,
104/104 verts ; `ruff`/`mypy` strict verts.

### Problème

Le serveur enregistre actuellement trois outils minimaux, tandis que le contrat
MCP cible en liste vingt-neuf.

### Travail attendu

1. Prioriser les outils nécessaires au bootstrap d'un agent : tâches, sessions,
   claims, décisions et AI Work Ledger.
2. Ajouter ensuite les outils de transfert ne manipulant que métadonnées et URLs
   signées.
3. Reporter les outils mémoire/Graphify/Context Package jusqu'à disponibilité des
   adaptateurs du Bloc B.
4. Uniformiser les erreurs machine-readable, filtres et limites.
5. Ajouter des tests MCP de contrat et d'authentification.

### Critères d'acceptation

- Chaque outil annoncé comme disponible possède un test de succès et d'erreur.
- Aucun gros contenu fichier ne transite par MCP.
- L'écart résiduel avec `TECH/07_MCP_CONTRACT.md` est documenté.

## Étape 6 — Construire le socle du Bloc B (P1 produit)

Volumineuse et hétérogène comme l'étape 4 en son temps : découpée en
sous-étapes indépendantes dans `docs/ROADMAP_STEP6_BREAKDOWN.md` (à cocher
au fil des clôtures, ce fichier n'entre pas dans le détail sous-étape par
sous-étape).

Statut : sous-étapes 6.1 à 6.6 closes (DEC-0024, DEC-0028, DEC-0029,
DEC-0030, DEC-0031, DEC-0032). 6.7 (`TransferClient`) reste ouverte —
l'étape entière n'est pas close.

### Ordre recommandé

1. `StudioApiClient`, configuration et stockage sécurisé du token machine.
2. Daemon local et heartbeat.
3. Outbox SQLite persistante avec idempotence et backoff borné.
4. Reconnexion et replay ordonné.
5. CLI minimale pour projets, tâches, sessions et claims.
6. Watchers Git et Godot.
7. `TransferClient`, état multipart local et reprise upload/download.

### Critères d'acceptation

- Un redémarrage du daemon ne perd aucune mutation en attente.
- Une coupure réseau suivie d'une reconnexion ne crée aucun doublon.
- Deux clients simulés observent le même état serveur sans dépendance LAN.

## Étape 7 — Compléter les tests d'acceptation stockage et offline (P2)

### Scénarios manquants prioritaires

- fichier multipart de 1 Go ;
- interruption à 50 %, redémarrage client et reprise ;
- URL signée expirée ;
- mauvais hash ;
- quota dépassé ;
- expiration et suppression ;
- téléchargement avec HTTP Range ;
- concurrence réelle de claims ;
- deux machines simulées sur des réseaux distincts ;
- replay offline complet avec tasks, events et AIWorkLog.

### Critères d'acceptation

- Tous les scénarios de `TECH/10_TEST_ACCEPTANCE.md` sont automatisés ou marqués
  comme tests manuels avec preuve, environnement et résultat daté.

## Étape 8 — Connaissance IA et expérience de collaboration (P2 produit)

### Travail attendu

1. Review Queue et interface AI Work Ledger.
2. Adaptateurs Obsidian et Graphify locaux, en lecture seule pour Qwen par défaut.
3. Génération de Context Packages.
4. Dashboard minimal cohérent avec API, MCP et CLI.
5. Notifications et timeline quotidienne.

### Critères d'acceptation

- Un agent peut charger un contexte ciblé via MCP sans synchroniser la mémoire
  privée d'un développeur.
- Les actions IA substantielles restent traçables par AIWorkLog/Event.

## Étape 9 — Producer, media et hardening final (P3)

### Travail attendu

1. Studio Producer, intégrations GitHub/build et workers.
2. RecordingProvider, markers et MarketingCandidate.
3. Observabilité, rate limiting et revue de sécurité.
4. Tests de charge et chaos légers.
5. Procédures d'exploitation, rotation/révocation et restauration périodique.

### Critères d'acceptation

- La définition de done globale du cahier des charges est démontrée sur deux
  postes et deux connexions Internet.
- Le système est observable, sauvegardable et restaurable.

## Étape 10 — Réconcilier documentation et état réel

### Travail attendu

1. Mettre à jour `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md` à partir de preuves
   vérifiables.
2. Ne cocher que les éléments réellement testés.
3. Ajouter pour chaque validation importante la commande, la date et
   l'environnement.
4. Maintenir cette roadmap à chaque clôture d'étape.

### Critères d'acceptation

- La documentation ne présente plus comme absents les contrats, fixtures,
  multipart ou tests déjà implémentés.
- Toute case cochée possède une preuve reproductible.
