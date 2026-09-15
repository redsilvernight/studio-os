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

Statut : **étape entièrement close** — sous-étapes 6.1 à 6.7 closes
(DEC-0024, DEC-0028, DEC-0029, DEC-0030, DEC-0031, DEC-0032, DEC-0033).

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

## Étape 7 — Compléter les tests d'acceptation stockage et offline (P2) — CLOS

Dixième et dernier scénario ("deux machines simulées sur des réseaux
distincts") fermé sans mock applicatif : deux `MachineModel`/`StudioApiClient`/
`OutboxStore` indépendants (aucun état local partagé), coupure réseau réelle
côté machine B, redémarrage simulé, transfert de fichier réel A→stockage→B,
rejeu idempotent sans doublon (claims inclus) : `docs/DECISIONS.md` DEC-0040,
`tests/client/test_two_machines_acceptance.py`. Les 10 scénarios "Tests
bout-en-bout"/"Tests transfert"/"Tests backend"/"Tests clients" de
`TECH/10_TEST_ACCEPTANCE.md` sont désormais tous automatisés ; "review et
résumé quotidien" (fin de la même ligne TECH/10) relève de l'étape 8, pas de
celle-ci.

### Scénarios manquants prioritaires

- ~~fichier multipart de 1 Go réel~~ — fermé (DEC-0038) :
  `tests/client/test_transfers_1gb_acceptance.py` (Postgres+MinIO réels, 1 GiB
  streamé par blocs de 1 Mio jamais alloué en mémoire, interruption réelle
  après 8/16 parts, redémarrage client simulé — nouvelles instances
  `StudioApiClient`/`OutboxStore`/`TransferClient` sur le même fichier
  SQLite —, reprise des 8 parts manquantes uniquement, vérification octet à
  octet par sha256, nettoyage MinIO/local garanti en `finally`) ;
- ~~interruption à 50 %, redémarrage client et reprise~~ — fermé (DEC-0033 :
  `tests/client/test_transfers.py::test_upload_multipart_resumes_after_interrupted_part`,
  interruption réseau + reprise sans réémission des parts terminées ;
  DEC-0037 : `tests/client/test_transfers_ttl_acceptance.py`, interruption
  après une part réelle, dépassement *réel* du TTL des URLs présignées,
  redémarrage client simulé — nouvelles instances
  `StudioApiClient`/`OutboxStore`/`TransferClient` sur le même fichier
  SQLite —, reprise avec vérification octet à octet) ;
- ~~reprise longue après expiration des URLs~~ — fermé (DEC-0037) :
  endpoint additif `POST /transfers/{id}/upload/refresh-parts`, voir
  `tests/api/test_transfers_multipart_refresh.py` (10 tests MinIO/Postgres
  réels) ;
- ~~URL signée expirée~~ — fermé (DEC-0034) : `tests/api/test_transfers_expired_url.py`
  (rejet réel MinIO, 403) + `tests/client/test_transfers.py` (`TransferClient`
  lève `TransferError`) ;
- ~~mauvais hash (Content-MD5)~~ — fermé (DEC-0025, preuve réelle
  préexistante) : `tests/api/test_transfers_storage.py`
  (`test_upload_rejected_by_minio_on_content_md5_mismatch`,
  `test_upload_complete_rejects_content_md5_mismatch_defense_in_depth`) ;
- ~~quota dépassé (et concurrence du quota)~~ — fermé (DEC-0019, preuve
  réelle préexistante) : `tests/api/test_transfers_quota.py`
  (`test_create_transfer_rejects_when_project_quota_exceeded`,
  `test_concurrent_creates_never_exceed_project_quota`) ;
- ~~expiration et suppression~~ — fermé (DEC-0020, preuve réelle
  préexistante) : `tests/api/test_transfers_expiration.py`
  (`test_worker_deletes_expired_transfer_from_db_and_minio`,
  `test_worker_rerun_is_idempotent`) ;
- ~~téléchargement avec HTTP Range~~ — fermé (DEC-0033, preuve réelle
  préexistante) : `tests/client/test_transfers.py::test_download_resumes_with_range_header` ;
- ~~concurrence réelle de claims~~ — fermé (DEC-0034) :
  `tests/api/test_claims_concurrency.py` (10 créations réellement
  concurrentes, invariant "jamais bloqué" vérifié contre Postgres réel) ;
- ~~deux machines simulées sur des réseaux distincts~~ — fermé (DEC-0040) :
  `tests/client/test_two_machines_acceptance.py` (deux `MachineModel`/
  `StudioApiClient`/`OutboxStore` indépendants sans état local partagé,
  coupure réseau réelle, redémarrage simulé, transfert de fichier réel,
  rejeu idempotent sans doublon) ;
- ~~replay offline complet avec tasks, events et AIWorkLog~~ — fermé
  (DEC-0039) : `tests/client/test_offline_replay_acceptance.py` (Postgres
  réel, hors-ligne simulé par un vrai `httpx.ConnectError`, 3 tasks + 2
  events + 1 AIWorkLog mis en queue via `OutboxStore`, redémarrage client
  simulé, replay réel, puis rejeu intégral vérifiant l'absence de doublon).

### Critères d'acceptation

- Tous les scénarios de `TECH/10_TEST_ACCEPTANCE.md` sont automatisés ou marqués
  comme tests manuels avec preuve, environnement et résultat daté.

## Étape 8 — Connaissance IA et expérience de collaboration (P2 produit)

Découpée en sous-étapes indépendantes dans `docs/ROADMAP_STEP8_BREAKDOWN.md`
(même principe que `docs/ROADMAP_STEP4_BREAKDOWN.md` et
`docs/ROADMAP_STEP6_BREAKDOWN.md`), avec l'état réel du dépôt vérifié avant
découpage et les questions de conception non tranchées par les documents
existants listées explicitement.

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

## Étape 11 — Consommateur universel (model-agnostic, rectifie Phase 1)

Rectification Phase 1 : DEC-0043 amendee (separation `auth_role` /
`harness` / `provider` / `model`, `agent_profile` = metadonnee optionnelle,
jamais whitelist), DEC-0044 supersedee par DEC-0043 (les quatre agents
specialises sont de l'outillage de developpement, voir
`docs/PRODUCT_VS_DEV_TOOLING.md`). `auth_role` reste la seule autorite
serveur ; aucun RBAC parallele. Les anciennes sous-phases MA-2 → MA-8,
centrees sur la canonisation des quatre agents de developpement, sont
abandonnees et remplacees par les sous-phases UC ci-dessous (prefixe UC pour
eviter toute collision avec les Étapes 1-10 et avec les MA abandonnees).

### Audit du consommateur universel (2026-09-15)

Agent simule : `harness = unknown-harness`, `provider = unknown-provider`,
`model = unknown-model`, sans `agent_profile`. Methode : lecture du coeur
(`services/`, `packages/`) + contrats `TECH/02-09`.

| Parcours | Inconnu OK ? | Verdict | Raison exacte / gap |
|---|---|---|---|
| Installation/configuration | partiel | PARTIAL | Client de reference Python/httpx generique ; mais prompts Bloc B et bootstrap rediges pour Claude, pas de guide d'integration externe → UC-6 |
| Identite/authentification | oui | PASS | Bearer machine provisionne hors-bande (`studio-admin`), aucun savoir harness/modele requis (DEC-0003/0011, `TECH/04`) |
| Decouverte des capacites | partiel | PARTIAL | Liste d'outils MCP + contrats TECH ; mais 4 outils memoire/graphe declares non implementes serveur (DEC-0042), pas d'index externe unique → UC-3 |
| API/MCP sous autorisation | oui | PASS | `auth_role` + ownership uniquement ; `agent_kind` chaine libre jamais lue par `authz.py` ; zero branche `if model/provider/harness` dans `services/` et `packages/` |
| Taches | oui | PASS | Endpoints generiques, `Idempotency-Key` standard |
| Events | oui | PASS | Enveloppe fixe, identite liee a la machine authentifiee (DEC-0035) |
| Worklogs | oui | PASS | Acteur generique user/agent, revue admin-only sur `auth_role` (DEC-0041) |
| Sync offline | protocole oui | PARTIAL | Replay idempotent cote serveur ; reimplementation client requise, reference Python uniquement (`TECH/08`) → UC-6 |
| Transferts | oui | PASS | URLs pre-signees directes vers MinIO/S3, jamais via FastAPI (DEC-0025) |
| Memoire/knowledge | partiel | PARTIAL | Contrat MCP declare (`TECH/07/09`) mais 4 outils manquants serveur ; adaptateurs locaux read-only existent (DEC-0042) → UC-3 |
| Sans modification du coeur | oui | PASS | Aucun couplage produit trouve dans le code (voir classification ci-dessous) |

### Classification des occurrences (2026-09-15)

- A — integration specifique legitime : pins `model` dans
  `.codex/agents/*.toml` (profil d'execution de l'outillage de dev, hors
  produit) ; mentions Claude/Qwen historiques figees (tracabilite).
- B — metadonnee/observabilite : `agent_kind` (chaine libre, jamais lue par
  l'autorisation) ; valeurs de fixtures `agent_kind="claude_code"` dans les
  tests (donnees, pas logique).
- C — couplage produit corrige par cette rectification : DEC-0044 (supersedee) ;
  valeurs `agent_profile` whitelistees en DEC-0043 v1 (amendee) ; roadmap
  MA-2 → MA-8 (remplace ci-dessous).
- C — couplage documentaire restant a corriger : `AI/02_AGENT_RULES.md`
  ("Claude orchestrateur" / "Qwen local" comme roles), `HUMAN/*` et bootstrap
  rediges pour Claude/Qwen → UC-4.
- D — historique a conserver : mentions Claude/Qwen dans DEC-0042 et
  breakdowns (contexte d'epoque, pas des regles).

### Sous-phases futures, dans l'ordre

- UC-1 Interface consommateur universelle : figer qu'un client sans
  `agent_profile` obtient l'interface complete de son `auth_role`
  (deja vrai en code ; test de conformance `unknown-harness` en UC-7).
- UC-2 Independance de l'authentification : verifier que le provisioning et
  le renouvellement restent sans savoir harness/modele. Rien a changer sauf
  preuve contraire.
- UC-3 Decouverte des capacites : exposer les 3 outils MCP locaux
  memoire/graphe read-only (DEC-0047, suite de DEC-0042 ; 8.3a),
  `studio_generate_context_package` DEFERRED avec condition (8.3b).
- UC-4 Documentation model-agnostic : `Claude`/`Qwen` utilises comme roles →
  termes fonctionnels generiques ; references historiques legitimes
  conservees (categorie D).
- UC-5 Metadonnees runtime : ajout additif `harness`/`provider`/`model`
  (chaines ouvertes, observabilite uniquement) et `agent_profile` optionnel
  sur `Agent`/`AIWorkLog` via `contract-change`, coexistence avec
  `agent_kind`. Ces champs ne doivent jamais entrer dans `authz.py`.
- UC-6 Guide d'integration externe : ecrire le parcours d'un developpeur
  tiers de zero (provisioning → premier event → premier transfert) sans
  connaissance interne Claude/Qwen/Codex ; valider qu'il suffit.
- UC-7 Tests de conformance : client fictif
  (`unknown-harness`/`unknown-provider`/`unknown-model`, sans profil)
  exercant taches, events, worklogs, sync et transferts ; echec si le coeur
  exige un savoir prealable.

### Critères d'acceptation

- A previously unknown AI agent/harness/provider/model can integrate with
  Studi'OS without modification of the Studi'OS core.
- Aucun identifiant de modele, provider, harness ou profil ne sert d'entree
  a une decision d'autorisation ou de capacite serveur.
- Le parcours UC-6 est executable par un tiers sans aide interne.
