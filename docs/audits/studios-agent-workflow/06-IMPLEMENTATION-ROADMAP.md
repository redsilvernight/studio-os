# Roadmap proposée — aucune implémentation engagée

Ce plan attend validation humaine de l'audit. Aucun commit, déploiement, changement de skill, mutation de tâche ou de session n'a été effectué. Les étapes ci-dessous ne sont pas des tâches créées dans Studio OS. Prioriser les corrections ciblées ; ne pas reconstruire les mécanismes existants.

## Préalable — établir la base d'intégration

Préserver les changements préexistants, identifier la révision de référence et la version réellement déployée. Distinguer le backlog Studio de l'état du checkout : les réponses compactes sont déjà implémentées localement alors que la tâche de suivi ressort encore créée. Identifier le propriétaire des six drifts Codex avant toute régénération. Aucun nettoyage automatique d'une modification utilisateur.

Livrable : matrice local/intégré/déployé et liste des modifications appartenant à l'implémentation future. Acceptation : aucune modification préexistante perdue, aucun secret publié.

## P0 — fiabilité de coordination et concurrence

### P0.1 — préserver les signaux au handoff

- **Fichiers :** `services/api/src/studio_api/services/handoff.py`, `sessions.py`, `sync.py` ; `services/mcp/src/studio_mcp/response_budget.py`, `tools/handoff.py` ; contrats `studio_contracts/{handoff,sync}.py` et TECH/02, TECH/07 selon solution.
- **Changement envisagé :** choisir une sémantique explicite de livraison/ack. Aucun curseur ne doit franchir un item dont le contenu n'est pas récupérable par le destinataire ou son successeur. Préserver réponse compacte, héritage curseur et idempotence.
- **Tests :** signal après le dernier sync client ; handoff compact ; réponse perdue ; retry même clé ; nouveau successeur ; dépassement budget/overflow ; plusieurs signaux et signal de handoff unique.
- **Acceptation :** chaque signal pertinent est récupérable au moins une fois et traité sans double effet ; aucune auto-ack invisible ; compact <=1000 si cette promesse est maintenue ; compatibilité des anciens clients explicitement traitée.
- **Dépendances :** décision de contrat, contract-change et revue contract-guardian avant merge. Ne pas généraliser verbose=true comme réparation permanente.

### P0.2 — prouver et sécuriser les writes concurrents

- **Fichiers :** `services/api/src/studio_api/services/tasks.py:157-178`, `sessions.py:464-475`, `handoff.py:264-270`, modèles concernés seulement si nécessaire.
- **Changement envisagé :** commencer par tests qui orchestrent deux transactions concurrentes ; puis CAS SQL/verrou/outil de versionnage déjà compatible avec le code voisin. Pas de migration DB présumée nécessaire.
- **Tests :** update même version avec deux sessions et barrière ; ack simultanés 10/20 ; handoff/update concurrent ; claim/start concurrency existants.
- **Acceptation :** un seul update concurrent accepté, conflit 409 cohérent ; curseurs jamais décroissants ; tests de replay inchangés. Si l'hypothèse n'est pas reproduite, documenter la protection réellement trouvée plutôt que patcher sans cause.
- **Dépendances :** PostgreSQL isolé, P0.1 pour curseur de handoff. Les tests séquentiels actuels ne suffisent pas.

## P1 — instructions, validations et économie de contexte

### P1.1 — propriétaire unique et projection courte

- **Fichiers :** `packages/studio-client/src/studio_client/{canonical,cli,adapters_check}.py`, adapters concernés, `tests/client/test_canonical_p3.py`, AGENTS généré ; script utilisateur `C:/Users/redsi/.codex/sync-claude-config.ps1` dans une intervention séparée autorisée.
- **Changement :** un propriétaire du bloc projet ; migration contrôlée des marqueurs hérités ; règles à portée référencées et chargées à la demande ; préserver les textes hors blocs.
- **Tests :** anciens deux blocs, copie orpheline connue, aucun bloc, texte utilisateur entre/après blocs ; deux générations identiques ; check Claude/Codex/OpenCode.
- **Acceptation :** une seule copie, AGENTS cible <8 Ko si compatible avec contenu utilisateur ; règles à portée non inlinées globalement ; aucun drift créé. L'objectif de taille reste subordonné à la conservation des instructions utiles.
- **Dépendances :** propriétaire du synchroniseur personnel, résolution des six drifts existants sans les écraser.

### P1.2 — un cycle commun et une branche audit explicite

- **Fichiers :** `.agents/rules/studio-protocol.md`, `.agents/skills/studio-{task,context,handoff}/SKILL.md`, références éventuelles ; descriptions MCP dans `server.py` ; tests protocole ; projections régénérées.
- **Changement :** suivi=start_work, observation/refresh=prepare_context ; cycle commun, aliases transitoires ; checkpoint log seulement s'il apporte une persistance intermédiaire ; final log via handoff.
- **Tests :** quatre parcours démarrage/reprise/audit/échec, reprise zéro historique ; signatures des exemples confrontées au registre ; déclencheurs anciens encore résolus.
- **Acceptation :** pas de lecture initiale double imposée, pas de mutation dans le scénario lecture seule, pas de log dupliqué systématique, pas de suppression de spécialités utiles.
- **Dépendances :** P0.1 avant promesse de livraison de signaux, P1.1 pour projections.

### P1.3 — tests purs réellement indépendants de l'infrastructure

- **Fichiers :** `tests/client/conftest.py:79-92`, `tests/api/conftest.py:60-74`, modules de fixtures stockage, tests MockTransport et inventaire.
- **Changement :** nettoyage DB/MinIO seulement pour les tests qui utilisent ces ressources ; préserver nettoyage et sécurité des vrais tests d'intégration.
- **Tests :** 37 tests `tests/client/test_api_client.py` sans DB/MinIO ; registres API introspectifs ; tests transferts en environnement isolé ; test de non-contamination entre cas.
- **Acceptation :** tests purs verts même si services absents, aucune tentative d'effacement stockage dans ces tests ; véritables tests infra explicitement marqués et nettoyés.
- **Dépendances :** environnement de test dédié pour prouver le nettoyage, pas production.

### P1.4 — preuve de complétion et profil de connexion

- **Fichiers :** skills workflow/handoff ; `studio_contracts/handoff.py`, `services/.../handoff.py` si enforcement choisi ; configuration de connexion par harnais hors source canonique pour profil ; tests contrats/profils.
- **Changement :** exiger evidence dans la procédure ; décider d'un enforcement serveur compatible/versionné ; sélectionner session pour travail courant, admin quand nécessaire.
- **Tests :** completion absente, rouge, audit avec finding en échec mais validation artefact réussie, code sans révision, CI requise ; tools/list des profils et call hors profil toujours autorisé/refusé selon véritables droits.
- **Acceptation :** aucun faux succès ; anciens clients pris en compte ; les outils admin restent découvrables par le chemin explicite ; pas de profil utilisé comme rôle.

## P2 — bords opérationnels et contrats

### P2.1 — retries et états partiels

- **Fichiers :** `idempotency.py`, `coordination.py`, `tools/claims.py`, tests de concurrence et injection de panne.
- **Changement :** d'abord mesurer/tester appels >30s et échecs entre commits ; documenter réconciliation batch ; comparer payload de coordination au replay si décidé. Ajouter lease/fencing seulement si le test justifie ce coût.
- **Acceptation :** récupération après vraie panne sans exécution simultanée du même effet ; même clé/payload retourne original ; mismatch explicite ; aucun doublon de signal ; claims déjà commit visibles et réconciliables.

### P2.2 — divulgation progressive, schémas et backlog

- **Fichiers :** handlers prioritaires `context/start_work/sync/handoff/decisions/claims`, modèles et tests schémas ; documentation de bibliothèque/résolution ; tâches serveur seulement dans une action distincte autorisée.
- **Changement :** ne pas refaire compaction existante ; vérifier version déployée ; filtres/pagination additionnels uniquement pour les listes réellement coûteuses ; préciser expiration comme présence et filtrage same-machine.
- **Acceptation :** schémas et métadonnées de release comparables, ordre/pagination stables, chiffres chars distincts des tokens, catalogue jamais rechargé sans nécessité.

### P2.3 — migration des outils deprecated

- **Fichiers :** `server.py`, `access_registry.py`, `deprecation.py`, allowlist de launch credentials, TECH/07 et consommateurs/tests.
- **Changement :** inventorier consommateurs puis migrer ; le sunset est une date autorisant le retrait, pas une raison suffisante pour l'appliquer. Préserver un chemin de libération privilégiée d'une tâche d'autrui quand nécessaire.
- **Acceptation :** aucune référence active aux cinq primitives avant retrait versionné ; tests et consommateurs migrés ; procédure de secours documentée. La tâche serveur de retrait existe déjà : ne pas en recréer une.

## P3 — expérimentation facultative

### P3.1 — pilote de coûts multi-harnais

Comparer tâches similaires sur Claude Code, Codex et OpenCode avec mêmes critères et version serveur : appels, volume sérialisé, tokens fournisseur si disponibles, latence, reprises, défauts et qualité de passation. Aucun objectif de gain arbitraire. Choisir les seuils après baseline ; vérifier que le profil court et les skills conditionnels ne dégradent pas la complétude.

### P3.2 — graph et mémoire à la demande

Comparer réutilisation d'un contexte relationnel existant à une requête répétée ; mesurer fraîcheur et utilité. Aucun nouvel index ou stockage de mémoire parallèle. Les rapports d'audit ne justifient pas une extraction sémantique automatique dans un graphe de production.

## Portes de sortie de l'implémentation future

Pour chaque unité : diff borné relu, tests ciblés appropriés, preuve de contrat si touché, projections check sans drift nouveau, Graphify exact changed paths si changement fonctionnel autorisé, puis preuve/handoff. Suite complète une fois avant intégration selon les règles du dépôt, dans un environnement isolé réellement disponible. Ne jamais confondre ces étapes proposées avec des validations exécutées dans cet audit.
