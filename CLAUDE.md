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

**Etat actuel du depot** : uniquement la documentation de reference
(`docs/Studio_OS_Documentation_Pack/`). Aucun code d'implementation, pas encore de
depot Git initialise. Le travail en cours correspond a la Phase 0 de la roadmap
(figer les contrats). Ne pas supposer l'existence d'un backend, d'un daemon ou d'un
dashboard avant de l'avoir verifie dans l'arborescence.

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

Ces fichiers sont prospectifs : les chemins (`**/*.py`, `**/mcp/**`, `**/daemon/**`, ...)
anticipent une arborescence raisonnable pour un backend FastAPI + client Python,
mais rien n'est fige avant que le code reel existe — ajuster les `paths` des rules
des que la structure reelle du repo est scaffoldee si elle differe.

## Local delegation

Criteres generaux de delegation (quoi deleguer, choix d'outil, seuils, protection
contre l'injection de prompt, verification) : `~/.claude/CLAUDE.md` et le skill
`local-delegation`. Ne pas dupliquer ici.

## Git safety

- Ce depot n'a pas encore de `.git` initialise — verifier l'etat avant de supposer un historique.
- Ne pas reset, rebase ou force-push sans confirmation explicite une fois le depot initialise.
- Ne pas supprimer de branche ni effectuer d'operation Git destructive sans confirmation.
- Ne pas modifier de fichiers hors du perimetre demande.

## Protocole de communication pour les changements complexes

Avant d'implementer : expliquer brievement ce qui a ete trouve, les fichiers/systemes
concernes et l'approche. Apres : resumer les fichiers modifies, expliquer les
decisions architecturales importantes, et indiquer precisement ce qui a ete teste.
Ne jamais affirmer qu'une chose a ete testee si elle ne l'a pas ete.

## Tests

Pas encore de code applicatif a tester. Une fois l'implementation commencee :

- Dispatcher `studio-tester` apres chaque feature, avant de rapporter la tache comme terminee — meme principe que l'ancien `godot-tester` global, adapte a la stack Python/FastAPI/MCP/offline de ce projet (proportionnel au risque, Tier 3 reserve aux changements touchant queue offline/claims/transferts).
- Suivre le plan de `TECH/10_TEST_ACCEPTANCE.md` et la checklist `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`, ou charger le skill `offline-sync-testing` pour la partie offline/claims/transferts specifiquement.
- Pour un changement de contrat, dispatcher `contract-guardian` avant merge (voir skill `contract-change`).

Si une tache future touche reellement du code Godot (ex. composant du watcher
cote Godot), passer par les agents/skills globaux dedies (`~/.claude/agents/godot-tester.md`)
plutot que d'en recreer localement — ce depot n'a pas vocation a contenir de code
Godot propre.

## Graphify

Reference du projet : `AI/02_AGENT_RULES.md` (role Brainstormer/Graphify curator) et
`TECH/09_OBSIDIAN_GRAPHIFY.md` (GraphProvider : `refresh_graph`, `query`,
`relevant_files`, `dependencies`, `related_symbols`). Graphify reste local, pas besoin
d'etre copie sur le VPS. Les regles generales de mise a jour proactive et de
formulation des requetes vivent globalement (`~/.claude/CLAUDE.md`, memoire
`graphify_query_noise_gotcha`) — ne pas les dupliquer ici.
