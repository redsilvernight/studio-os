# Interfaces des outils personnels et preuves d'exécution

Tâche Studi’OS : `22d72053-92d7-494a-8a19-2b276de1635b`.
Référence vérifiée le 28 octobre 2026 sur `40516c8c`.

Cette note définit les informations attendues à la frontière d'une délégation
vers un outil personnel. Elle réutilise les interfaces existantes de Studi’OS
et décrit les exigences des futurs adaptateurs. Elle n'ajoute ni endpoint,
ni schéma partagé, ni garantie de capacité d'un backend externe.

## Périmètre et responsabilités

Studi’OS attribue le travail à un projet, une tâche, un agent et une session,
conserve les références de preuves et vérifie les critères de clôture.
Le runner gère le processus qu'il lance. L'outil externe reste responsable
de sa file, de ses jobs distants, de son ordonnanceur et de ses ressources.
Un arrêt du processus appelant ne prouve pas l'arrêt d'un job dans cet outil.

Les contrats publiés restent ceux du [TaskLaunch et du handoff](Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md)
et du [MCP](Studio_OS_Documentation_Pack/studio_os_docs/TECH/07_MCP_CONTRACT.md).
Les libellés ci-dessous servent à l'échange avec un adaptateur ; ils ne sont
pas de nouveaux statuts de TaskLaunch, de tâche ou de session.

## Quatre interfaces attendues

### Résultat et traçabilité

Chaque délégation conserve les identifiants Studi’OS disponibles
(`project_id`, `task_id`, `agent_id`, `session_id`) et le `task_launch_id`
si elle provient d'un lancement. L'identifiant du job externe est conservé
séparément ; une reprise réutilise cet identifiant pour consulter le job,
sans le soumettre une deuxième fois à l'aveugle.

| Information | Exigence de l'adaptateur | Existant vérifié |
|---|---|---|
| État observé | Distinguer accepté/en attente/en cours/terminal ; indiquer la source et la date d'observation. Une réponse manquante reste inconnue. | TaskLaunch porte son propre cycle ; aucun mapping générique des jobs externes n'est livré ici. |
| Résultat processus | Code réel ou absence explicite, durée, début/fin, timeout et annulation séparés. | [LaunchResult et RunningLaunch](../packages/studio-client/src/studio_client/daemon/launch_runner.py). |
| Preuves de commandes | Commande exacte, code réel, référence de log ; signaler sortie tronquée ou preuve manquante. Le code du harnais ne remplace pas celui des commandes. | [ExecutionEvidence](../packages/studio-client/src/studio_client/daemon/execution_evidence.py) lit un sous-ensemble borné d'événements structurés ; ce n'est pas un protocole universel. |
| Artefacts | Références consultables, fichiers changés et vérifications réellement exécutées ; aucun secret ni octet de gros fichier dans MCP. | [CompletionEvidence](../packages/studio-contracts/src/studio_contracts/completion.py) et AI work/handoff. |

`ExecutionEvidence.validation` peut valoir `failed`, `environment_unavailable`
ou `unverified`. L'absence d'échec détecté ne produit pas `passed`.
Le parseur conserve au plus 64 Ki caractères, 512 documents et 20 codes de
commande ; ses limites doivent accompagner toute interprétation du résultat.
La sortie de `LaunchResult` est bornée mais pas encore expurgée : utiliser
le chemin de rapport du [launch executor](../packages/studio-client/src/studio_client/daemon/launch_executor.py)
avant exposition, jamais publier directement sa sortie brute.

### Timeout

L'appelant fournit une attente bornée. L'adaptateur distingue attente en file,
durée d'exécution et délai de transport ; leur portée et leur unité doivent
être explicites. Aucun délai de file ne doit être présenté comme du calcul.

Le runner existant applique `RunningLaunch.wait(timeout)` au processus lancé
et tente de tuer son arbre à l'échéance. Il retourne `timed_out=true` et
`exit_code=null` ; le launch executor rapporte `failed` avec
`reason_code=expired_timeout`. Le statut serveur `expired` est distinct.

Pour un job externe, un timeout d'appel signifie seulement que l'attente a
expiré. L'adaptateur doit ensuite consulter le job et, si l'annulation est
supportée et demandée, en vérifier l'effet. Sans preuve terminale, déclarer
« état externe inconnu, ressources potentiellement encore occupées ».
Ne pas réessayer un travail ayant des effets sans vérifier le job initial.

### Annulation

L'adaptateur annonce sa capacité : annuler avant démarrage, interrompre en
cours, ou annulation non supportée. Il distingue demande envoyée,
accusé de réception et arrêt observé ; un accusé ne suffit pas à prouver
la libération de la file ou d'un bail GPU.

Pour TaskLaunch, le daemon observe `cancelled`/`expired` par lecture de son
statut et arrête le processus. Il ne réécrit pas un résultat terminal concurrent.
Voir les [tests du launch executor](../tests/client/test_launch_executor.py)
et [DEC-0177](decisions/DEC-0177-aib-r3-annulation-d-un-lancement-en-cours-livree-par-get.md).
Selon DEC-0213, une annulation n'achève ni la tâche ni la session ni les claims :
une session encore ouverte reste à vérifier et nécessite son propre handoff.

### Préflight

Avant soumission, relever disponibilité de l'outil, version/capacités,
commande et dépendances requises, infrastructures nécessaires, budget de
ressources et politique d'attente. Un contrôle incapable de vérifier un point
le déclare inconnu. Il ne démarre pas de service et ne recharge pas de modèle
pour rendre son propre contrôle vert.

Le précontrôle workers est suivi par la tâche terminée
`e33342ea-075b-4376-93c2-0340401f3ef5` : pytest absent, PostgreSQL indisponible
et Docker inaccessible sont classés `environment_unavailable` dans les cas
couverts ; une commande échouée n'est pas validée par un harnais sortant à 0.
Sources : [tests ExecutionEvidence](../tests/client/test_execution_evidence.py),
[préflight des tests](../tests/harness/test_test_env_preflight.py),
[test-env.ps1](../scripts/test-env.ps1).
Le préflight de développement [dev_preflight.py](../scripts/dev_preflight.py)
reste un contrôle distinct du dépôt, pas une preuve de disponibilité de Bonsai.

## Lots, contention et travaux externes à prendre en charge

L'[admission par lots Studi’OS](../services/api/src/studio_api/routers/admission.py)
ne garantit ni FIFO ni priorité interactive dans un outil personnel.
Une future soumission par lots doit conserver un identifiant et un résultat
par élément, signaler les succès partiels, limiter la concurrence et permettre
de consulter les éléments survivants après un timeout ou une annulation.

Les unités ci-dessous sont consignées comme travaux externes à attribuer,
pas comme des tickets serveur créés ni des fonctions déjà livrées.
Le responsable est un rôle de maintenance ; aucune personne n'est assignée
sans accord et aucune configuration personnelle n'est modifiée ici.

| Unité externe | Responsable attendu | Preuve requise avant intégration | État constaté dans cette tâche |
|---|---|---|---|
| File Bonsai/Local AI Hub : lots et attente | Mainteneur du Hub/Bonsai | Identifiants par élément, politique FIFO/priorité documentée, concurrence bornée, succès partiels et refus de surcharge testés. | À attribuer ; non vérifié sur le backend. |
| Annulation et timeout des jobs Hub/Bonsai | Mainteneur du Hub/Bonsai | Consultation du job après timeout ; annulation en file/en cours ; arrêt et libération du bail observés ; absence de job orphelin. | À attribuer ; aucune garantie externe établie. |
| Contention avec la voix interactive | Mainteneurs du Hub et du client voix | Scénario de requête longue + voix, délais mesurés, arbitrage explicite et absence de famine ; budget RAM/VRAM vérifié avant charge. | À attribuer ; aucun essai de charge exécuté ici. |
| Jobs OpenCode, résultats et arrêt | Mainteneur du dispatch OpenCode | Mapping job/élément vers résultat et commandes, logs bornés, capacités d'annulation, consultation après délai et relance sans doublon. | À attribuer ; l'adaptateur headless Studi’OS ne prouve pas ces capacités du dispatch externe. |
| Consommation des preuves dans Studi’OS | Mainteneur du client Studi’OS | Mapping explicite vers les interfaces existantes, tests de compatibilité et de sécurité avant ajout d'un adaptateur. | Interfaces cadrées ici ; aucun nouvel adaptateur implémenté. |

Avant de démarrer une unité externe : rechercher un ticket dans le projet
propriétaire, réutiliser son UUID s'il existe, sinon faire attribuer/créer
le suivi par son responsable autorisé. Reporter cet UUID et les preuves
dans le handoff. Aucun UUID externe n'est établi par cette note.

## État outil et clôture métier

| Observation | Interprétation autorisée |
|---|---|
| L'outil répond `completed` mais une commande requise échoue | Exécution non validée ; conserver le code et le diagnostic. |
| Harnais à 0, aucune commande vérifiable | Résultat processus reçu ; validation `unverified`. |
| Dépendance absente ou infrastructure inaccessible | Échec d'environnement dans les cas identifiés ; pas de preuve du livrable. |
| Timeout/annulation sans arrêt externe observé | Travail externe non résolu ; aucun succès ni libération supposée. |
| Livrable vérifié et critères satisfaits | Handoff avec preuves ; clôture selon le type de travail et les gates applicables. |

La [preuve de clôture](../packages/studio-contracts/src/studio_contracts/completion.py)
est déclarative : `ready` n'est pas une approbation humaine ni une vérification
du dépôt par le serveur. Les états implémenté, testé, intégré et déployé
restent séparés. Vérifier le contrat réellement annoncé par le serveur connecté
avant d'envoyer un paramètre optionnel `completion` ; sinon persister les
preuves dans `summary`/AI work sans prétendre à une validation serveur.

## Vérification de ce cadrage

Le livrable de cadrage couvre les quatre interfaces définies, la matrice des
responsabilités et les règles de preuve ci-dessus. La mise en œuvre externe
nécessite ses propres tickets et validations ; elle ne bloque pas la livraison
de cette note de cadrage. Les tests existants cités servent de points de reprise,
pas de résultats nouvellement exécutés. Aucun test de Bonsai, de priorité voix
ou de dispatch OpenCode n'est revendiqué.
