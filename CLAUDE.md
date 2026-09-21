# Studio OS — Instructions Claude Code

## Langue

Communiquer en français, sauf demande explicite contraire. Le code, les noms de
fichiers, commandes et identifiants techniques restent dans leur langue d'origine.

## Mission et périmètre

Studio OS coordonne deux développeurs distants et leurs outils autour d'un VPS
central : API, MCP, PostgreSQL, stockage objet et, à terme, dashboard et workers.
Il relie Git/GitHub, Godot, agents IA, Graphify, Obsidian, sessions, builds,
enregistrements et transferts. Ce n'est ni un IDE, ni un moteur de jeu, ni un
remplacement de Git, ni un partage de disque, ni un outil de surveillance.

Ne jamais déduire l'état courant depuis ce fichier, y compris l'avancement des
Blocs A/B ou d'un composant donné (backend déployé, daemon, dashboard). Le
vérifier avec `git status`, l'arborescence, les tests et, lorsqu'il existe,
l'état Studio OS.

## Sources de vérité

Ordre de confiance :

1. contrats et décisions validées ;
2. état courant de Studio OS ;
3. Git local et GitHub ;
4. Graphify local ;
5. mémoire projet/studio ;
6. hypothèses.

Pour une implémentation, partir de
`docs/Studio_OS_Documentation_Pack/studio_os_docs/00_README.md`, puis lire
uniquement les références qu'il route vers la tâche. Consulter systématiquement
`docs/DECISIONS.md` avant une décision structurante. La roadmap corrective issue
de l'audit est `docs/ROADMAP_CORRECTIONS_AUDIT.md` ; elle complète la roadmap
normative, sans la remplacer.

## Invariants non négociables

- Le VPS est la source d'état partagé ; aucune dépendance LAN, SMB ou IP directe
  entre les postes.
- Les gros fichiers passent directement par S3/MinIO avec URLs pré-signées et
  multipart, jamais via FastAPI ou MCP.
- Les Resource Claims avertissent mais ne bloquent jamais Git.
- Les clients doivent tolérer l'offline et rejouer les écritures de façon
  idempotente.
- Les contrats API, Event, Auth/Sync et Data Model sont versionnés ; aucun
  changement silencieux.
- Toute action IA substantielle est traçable par AIWorkLog/Event.
- Qwen reste en lecture seule sur la mémoire partagée par défaut.
- Aucune mémoire privée n'est synchronisée et aucun transfert non expiré n'est
  supprimé sans politique explicite.
- Ne jamais construire un backend parallèle dans le Bloc B.

## Cycle de travail

Avant une modification substantielle :

1. lire `projects/studio-os/CURRENT.md` puis `SUMMARY.md` du vault AI-Memory
   (MCP `obsidian-memory`) ; pour une question de relations, `graphify query`
   via `pwsh -NoProfile -File scripts/graphify-studio.ps1`, vocabulaire expansé ;
2. vérifier Git et l'état réel du projet ;
3. consulter la tâche, les décisions et les claims/conflits disponibles ;
4. cibler les fichiers avec `rg` ou Graphify avant un balayage large ;
5. annoncer brièvement le périmètre et l'approche.

Après la modification :

1. exécuter une validation proportionnelle au risque ;
2. faire intervenir `studio-tester` après chaque feature ;
3. faire intervenir `contract-guardian` pour tout changement de contrat ;
4. consigner fichiers, tests, résultats et limites sans inventer de validation ;
5. mettre Graphify à jour directement, une seule fois, avec les chemins exacts
   modifiés ; appeler ensuite `brainstormer` uniquement si le lot contient une
   connaissance durable candidate ou change l'état de reprise, avec faits et
   preuves regroupés dans un seul mandat. Brainstormer ne met jamais Graphify à jour.

Pour une architecture Cloud/Core ↔ client local non triviale, utiliser
`studio-architect`. Pour une cause racine offline, idempotence, claims ou
transferts incertaine, utiliser `sync-debugger`.

## Règles, skills et tests

La source canonique vit dans `.agents/` : règle permanente
(`.agents/rules/studio-protocol.md`), skills (`studio-context`, `studio-task`,
`studio-decision`, `studio-handoff`, `graphify`, `contract-change`,
`offline-sync-testing`), définitions d'agents (`.agents/definitions/`).
Les règles détaillées sont projetées depuis `.agents/rules/` vers
`.claude/rules/` (ne pas les recopier ici) ; les configurations
`.claude/agents/` sont générées (`studio adapters check` en CI).

La politique globale de délégation locale vit dans `~/.claude/CLAUDE.md` et le
skill `local-delegation`. Pour les critères d'acceptation, utiliser
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/10_TEST_ACCEPTANCE.md` et
`docs/Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`.
Ne jamais affirmer qu'un environnement externe, PostgreSQL, MinIO ou Docker a été
testé pendant la tâche sans l'avoir réellement exécuté.

## Sécurité Git

- Préserver les changements existants et ignorer les modifications hors périmètre.
- Ne pas reset, rebase, force-push, supprimer une branche ou effectuer une autre
  opération destructive sans confirmation explicite.
- Vérifier `git status` et `git log` au lieu de se fier à une note historique.

## Graphify

Le graphe de ce dépôt est obligatoirement centralisé dans
`E:\Graphify\Studio-OS\graphify-out\`. Aucun `graphify-out/` ne doit rester à la
racine du dépôt.

- Toute commande Graphify pour ce dépôt doit passer par
  `pwsh -NoProfile -File scripts/graphify-studio.ps1 <commande>`. Ne jamais
  appeler directement `graphify` ou `graphify.exe` : le lanceur définit
  `GRAPHIFY_OUT=E:\Graphify\Studio-OS\graphify-out` avant le chargement du
  programme et échoue si un `graphify-out/` local existe ou apparaît.
- Garder comme racine source réelle
  `C:\Users\redsi\Documents\Coding\Projet\Studi'os`.
- Pour un build manuel, passer la racine source réelle comme argument au lanceur
  projet ; ne pas changer la destination avec `--out` ou `--output`.
- Suivre `.agents/skills/graphify/SKILL.md` ; ne jamais envoyer une question brute
  à `graphify query`, `path` ou `explain` sans expansion contrôlée du vocabulaire.
- Si un graphe local apparaît par erreur, transférer le résultat à l'emplacement
  central puis retirer uniquement ce dossier local après vérification des chemins.
- Pour une question sur le code, préférer `path`/`explain`/`query` (vocabulaire
  expansé, jamais la question brute) à un `grep` large — sous-graphe ciblé,
  généralement bien plus petit que `GRAPH_REPORT.md` ou une recherche texte.
  Si `graphify-out/wiki/index.md` existe, l'utiliser pour la navigation large
  plutôt que de parcourir les sources brutes ; ne lire `GRAPH_REPORT.md` que
  pour une revue d'architecture large ou si `query`/`path`/`explain` ne
  suffisent pas. Toujours via le lanceur, jamais `graphify` en direct.

Graphify est local et ne doit pas être copié sur le VPS. Les interfaces cibles
(`refresh_graph`, `query`, `relevant_files`, `dependencies`, `related_symbols`)
sont définies dans
`docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/09_OBSIDIAN_GRAPHIFY.md`.
