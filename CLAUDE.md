# Studio OS — Claude Code Instructions

## Communication

- Always communicate with the user in French unless the user explicitly asks for another language.
- Code, variable names, file names, commands, and technical identifiers may remain in their original language.
- Explanations, analysis, summaries, questions, and implementation reports must be written in French.

## Le projet

Studio OS est la couche de coordination commune d'un studio de jeu video de deux
developpeurs travaillant a distance sur des reseaux differents. Il relie humains,
Claude Code, Qwen local, agents specialises, Git/GitHub, Godot, Graphify, Obsidian,
enregistrements de sessions, builds, marketing et transferts de fichiers autour d'un
VPS central (etat partage, API, MCP, stockage objet).

Studio OS n'est **pas** un IDE, ni un moteur de jeu, ni un remplacement de Git, ni un
outil de surveillance de productivite, ni un partage de disque reseau, ni une IA
unique qui controle tout. Il ne code pas de jeu : il code la plateforme qui relie les
outils existants.

**Etat actuel du depot** : depot Git initialise (`origin` configure). Scaffold
du Bloc A (Cloud/Core) en place : `packages/studio-contracts/` (schemas
Pydantic v2 des 4 contrats), `services/api/` (FastAPI + SQLAlchemy async +
Alembic — projects/tasks/sessions/claims/decisions/agents/ai-work/heartbeats/
events/transfers/provisioning), `services/mcp/` (serveur MCP minimal, 3 tools
reels), `docker/` (compose Caddy/API/MCP/Postgres/MinIO), `contracts/fixtures/`
(mocks partages) et `tests/` (33 tests : contrats + `tests/api/` — auth,
tasks, claims, events, decisions, ai-work, heartbeats, projects, provisioning,
contre un vrai Postgres). Aucun daemon local, watcher, CLI, dashboard,
Graphify/Obsidian adapter, recorder ni Producer UI (Bloc B) — pas encore
construits. Provisioning (`projects`/`machines`/`users`) implemente
(DEC-0011/DEC-0012) : `POST /projects` (role `admin`/`developer`),
`POST /machines`, `POST /machines/{id}/revoke`, `POST /users` (role `admin`,
via la dependance `require_roles`) ; le tout premier admin/machine se cree
hors-bande avec la CLI serveur `studio-admin`
(`services/api/src/studio_api/admin_cli.py`, `uv run studio-admin ...` depuis
`services/api/`). Voir `docs/DECISIONS.md` pour les choix techniques non
tranches par la documentation et fixes pendant ce scaffold (DEC-0001 a
DEC-0014). Le travail correspond a la Phase 1 de la roadmap (Core utilisable)
en cours. PostgreSQL reel a ete verifie sur cette machine de dev (PostgreSQL
18 installe localement via `scoop`, pas de service Windows enregistre —
demarrer avec `pg_ctl start -D <chemin scoop persist>\data` avant
`uv run pytest` ; migrations Alembic + `tests/api/` tournent contre ce
Postgres local). MinIO/S3 (`StorageProvider`, presigning + multipart) a ete
valide reellement (DEC-0013) via un MinIO compile localement — 
`tests/api/test_transfers_storage.py`. Ce MinIO local n'est pas lance en
permanence : le redemarrer (identifiants par defaut de `Settings`, bucket
`studio-transfers` a recreer via boto3 `create_bucket`) avant de relancer
ces 4 tests specifiquement.

Docker Desktop est desormais installe sur cette machine (DEC-0014, WSL2)
et `docker/docker-compose.yml` a ete verifie reellement une fois (Postgres/
MinIO/API/MCP/Caddy, deux bugs corriges — images `minio/*` introuvables sur
Docker Hub → `quay.io/minio/*`, et `api.Dockerfile` qui n'installait pas les
dependances du workspace uv). Il n'est PAS laisse tourner en permanence
(`docker compose down` fait apres validation) — ne pas supposer qu'il
tourne sans verifier (`docker compose ps` depuis `docker/`). Aucune
migration Alembic automatique au demarrage du conteneur `api` : lancer
manuellement `docker compose exec api sh -c "cd services/api && python -m
alembic upgrade head"` sur une base fraiche avant tout premier
`studio-admin bootstrap-admin`.
Ne pas supposer l'existence d'un backend deploye, d'un daemon ou d'un
dashboard avant de l'avoir verifie dans l'arborescence — le scaffold n'a pas
ete deploye.

## Source de verite

Toute decision d'implementation doit s'appuyer sur
`docs/Studio_OS_Documentation_Pack/studio_os_docs/`, pas sur des suppositions.
Ordre de lecture pour une IA (voir `00_README.md` pour le detail complet) :
`AI/01_AI_OPERATING_REFERENCE.md` → `AI/02_AGENT_RULES.md` →
`AI/03_CONTEXT_BOOTSTRAP.md` → `TECH/01_ARCHITECTURE.md` → contrats
(`TECH/02` a `TECH/04`) → `TECH/05_DATA_MODEL.md` → `TECH/06..09` → `TECH/10_TEST_ACCEPTANCE.md`
→ `IMPLEMENTATION/01_ROADMAP.md` et les prompts de bloc.

## Principes non negociables

- Le serveur central (VPS OVH) est la source d'etat partagee, jamais une machine de developpeur.
- Aucune dependance LAN, SMB ou IP directe entre les deux postes.
- Les gros fichiers transitent par un stockage objet S3/MinIO (URLs pre-signees, multipart) — jamais proxyfies par FastAPI.
- Les Resource Claims sont des soft locks : ils avertissent, ils ne bloquent jamais Git.
- Qwen est lecture seule sur la memoire partagee par defaut.
- Toute action IA substantielle doit etre tracable (AIWorkLog / Event).
- Les contrats API, evenements, auth et sync sont versionnes — pas de modification silencieuse.
- Les clients doivent tolerer une coupure Internet temporaire (offline queue, resynchronisation idempotente).
- Pas de backend parallele, pas de synchronisation de memoire privee, pas de suppression automatique d'un transfert non expire sans politique explicite.

## Cycle de tache IA

Avant une modification substantielle : recuperer la tache et l'etat du projet,
verifier claims/conflits, respecter les decisions (DEC-XXXX) deja validees, cibler
les fichiers via Graphify avant un balayage massif. Apres : executer, tester,
consigner fichiers/tests/resultat modifies, poser l'etat de review, emettre les
evenements pertinents. Ne jamais inventer l'etat d'un autre developpeur ou supposer
un acces direct a son poste — interroger Studio OS.

Hierarchie de confiance en cas de conflit d'information : contrats/decisions validees
> etat courant Studio OS > Git local/GitHub > Graphify local > memoire projet/studio
> hypotheses de l'agent.

## Architecture cible (pour l'implementation)

- **VPS** : Caddy, FastAPI, MCP server, PostgreSQL, MinIO/S3, Dashboard, workers.
- **Chaque poste** : daemon Studio, CLI Studio, watcher Git, watcher Godot, adaptateur
  Graphify, adaptateur Obsidian, recording provider, file d'attente offline SQLite.
- Voir `TECH/01_ARCHITECTURE.md` pour la repartition exacte des responsabilites
  serveur/client et `IMPLEMENTATION/02_BLOCK_A_PROMPT.md` /
  `03_BLOCK_B_PROMPT.md` pour le decoupage Cloud/Core vs client local.

## Investigation

- Glob/Read/Grep pour les recherches simples.
- Graphify pour l'analyse architecturale une fois du code present (voir `.claude/skills/graphify/`). Le depot est actuellement du Markdown pur : le support natif Graphify s'applique directement, le contournement sidecar GDScript ne concerne pas ce depot (il ne contient pas de code Godot — Godot n'est ici qu'un systeme externe surveille par un watcher client).
- Ne pas relancer la meme requete Graphify plusieurs fois.
- Pour une architecture complexe ou multi-bloc (Cloud/Core ↔ Local Client), dispatcher l'agent `studio-architect` plutot que de raisonner seul sur l'ensemble du repo.

## Agents, rules et skills du projet

Reconstruits pour Studio OS (les anciens, herites d'un template de jeu Godot,
ont ete supprimes) :

- **Agents** (`.claude/agents/`) : `studio-architect` (analyse architecture Cloud/Core
  et Local Client avant changement non trivial), `contract-guardian` (verifie
  qu'un changement de contrat API/Event/Auth-Sync/Data Model est additif ou
  correctement versionne avant merge), `sync-debugger` (root-cause sur bugs
  offline/idempotence/claims/transferts), `studio-tester` (validation
  proportionnelle au risque apres une feature — contrats, tests, reprise offline).
- **Rules** (`.claude/rules/`, chargees automatiquement sur les chemins concernes) :
  `python-conventions.md` (async/typing/Pydantic v2), `contracts.md` (discipline
  additif/breaking sur les 4 contrats), `database.md` (UUID, `updated_at`/version,
  claims TTL, migrations reversibles), `mcp-tools.md` (convention `studio_*`,
  jamais de gros fichier via MCP), `offline-sync.md` (outbox SQLite, idempotence,
  dead_letter), `storage-transfers.md` (jamais de proxy FastAPI, multipart
  64-128 MiB, URLs signees 10-30 min).
- **Skills** (`.claude/skills/`) : `graphify` (inchange), `contract-change`
  (processus pour modifier un contrat sans casser l'autre Bloc), `offline-sync-testing`
  (checklist de validation offline/claims/transferts, alignee sur
  `TECH/10_TEST_ACCEPTANCE.md`).

Les chemins (`**/*.py`, `**/mcp/**`, `**/daemon/**`, ...) ont ete verifies contre
la structure reelle scaffoldee (`services/api/`, `services/mcp/`,
`packages/studio-contracts/`) — `.claude/rules/storage-transfers.md` a ete
elargi (`**/*transfer*.py`) pour couvrir `services/transfers.py`/`routers/transfers.py`
qui ne matchaient pas le pattern initial. Le Bloc B (`daemon/`, `cli/`, `watchers/`)
n'existe pas encore : ces `paths` restent prospectifs jusqu'a son scaffold.

## Local delegation

Criteres generaux de delegation (quoi deleguer, choix d'outil, seuils, protection
contre l'injection de prompt, verification) : `~/.claude/CLAUDE.md` et le skill
`local-delegation`. Ne pas dupliquer ici.

## Git safety

- Depot Git initialise (`origin` configure) — verifier `git status`/`git log` avant de supposer l'etat plutot que de se fier a une note perimee ici.
- Ne pas reset, rebase ou force-push sans confirmation explicite.
- Ne pas supprimer de branche ni effectuer d'operation Git destructive sans confirmation.
- Ne pas modifier de fichiers hors du perimetre demande.

## Protocole de communication pour les changements complexes

Avant d'implementer : expliquer brievement ce qui a ete trouve, les fichiers/systemes
concernes et l'approche. Apres : resumer les fichiers modifies, expliquer les
decisions architecturales importantes, et indiquer precisement ce qui a ete teste.
Ne jamais affirmer qu'une chose a ete testee si elle ne l'a pas ete.

## Tests

Un premier scaffold Bloc A existe (`tests/`, `pytest`) — voir l'etat du depot
ci-dessus. Une fois l'implementation continuee :

- Dispatcher `studio-tester` apres chaque feature, avant de rapporter la tache comme terminee — meme principe que l'ancien `godot-tester` global, adapte a la stack Python/FastAPI/MCP/offline de ce projet (proportionnel au risque, Tier 3 reserve aux changements touchant queue offline/claims/transferts).
- Suivre le plan de `TECH/10_TEST_ACCEPTANCE.md` et la checklist `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`, ou charger le skill `offline-sync-testing` pour la partie offline/claims/transferts specifiquement.
- Pour un changement de contrat, dispatcher `contract-guardian` avant merge (voir skill `contract-change`).

Si une tache future touche reellement du code Godot (ex. composant du watcher
cote Godot), passer par les agents/skills globaux dedies (`~/.claude/agents/godot-tester.md`)
plutot que d'en recreer localement — ce depot n'a pas vocation a contenir de code
Godot propre.

## Graphify

**Sortie centralisee, obligatoire : ce depot ne doit JAMAIS contenir de dossier
`graphify-out/`.** Tout le graphe (build initial ou `--update`) doit atterrir
dans `E:\Graphify\Studio-OS\graphify-out\` — voir
`~/.claude/references/graphify-centralized-output.md` pour le mecanisme exact.
En pratique :
- Pipeline manuelle (SKILL.md, premier build complet) : executer chaque bloc
  bash/python avec `cwd = E:\Graphify\Studio-OS` (PAS la racine du depot), et
  passer le vrai chemin du projet (`C:\Users\redsi\Documents\Coding\Projet\Studi'os`)
  comme `INPUT_PATH` partout ou le step doit lire les fichiers source.
- CLI graphify ou `graphify_incremental_update.py` : definir la variable
  d'environnement `GRAPHIFY_OUT=E:\Graphify\Studio-OS\graphify-out` (chemin
  absolu) avant la commande ; `--root`/le chemin du projet reste le vrai
  chemin du depot.
- Si un `graphify-out/` apparait quand meme a la racine du depot (skill
  invoque sans cette precaution), c'est un bug de procedure : deplacer son
  contenu vers `E:\Graphify\Studio-OS\graphify-out\` (en ecrasant l'ancien
  s'il est plus a jour) puis supprimer le dossier local - ne jamais le
  laisser trainer dans le depot.

Reference du projet : `AI/02_AGENT_RULES.md` (role Brainstormer/Graphify curator) et
`TECH/09_OBSIDIAN_GRAPHIFY.md` (GraphProvider : `refresh_graph`, `query`,
`relevant_files`, `dependencies`, `related_symbols`). Graphify reste local, pas besoin
d'etre copie sur le VPS. Les regles generales de mise a jour proactive et de
formulation des requetes vivent globalement (`~/.claude/CLAUDE.md`, memoire
`graphify_query_noise_gotcha`) — ne pas les dupliquer ici.
