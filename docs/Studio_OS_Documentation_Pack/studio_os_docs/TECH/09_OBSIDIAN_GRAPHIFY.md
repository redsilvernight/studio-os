# Obsidian & Graphify Integration

## Memoire
Trois niveaux: private, project, studio. Private n'est jamais synchronise automatiquement. Project/Studio peuvent etre proposes puis approuves.

### MemoryProvider
search, read, propose, write_if_authorized, append_task_log, create_decision_note.

Implémentation Bloc B (roadmap 8.2, DEC-0042) :
`packages/studio-client/src/studio_client/knowledge/` — `search`/`read`
seuls sont effectifs (`VaultMemoryProvider`), les écritures sont déclarées
mais refusées (`write_unsupported`, boucle d'approbation serveur en 8.4/8.5),
portée fermée par défaut via `ClientConfig` (`STUDIO_CLIENT_KNOWLEDGE_*`).

### Qwen
Lecture seule sur project/studio par defaut.

## Graphify
Graphify est local et n'a pas besoin d'etre copie sur le VPS.

### GraphProvider
refresh_graph, query, relevant_files, dependencies, related_symbols.

Implémentation Bloc B (roadmap 8.2, DEC-0042) : `GraphifyGraphProvider` lit
directement `graph.json`/`manifest.json` du `graphify-out` centralisé —
`query`, `relevant_files`, `dependencies`, `related_symbols` effectifs avec
signalement de fraîcheur (`stale`), `refresh_graph` explicitement non
supporté (reconstruction pilotée par la conversation principale).

## Context Package
Le serveur compose contexte partage; le client complete avec Git, Graphify, fichiers et memoire locale. Manifest versionne et trace les sources.

## Decisions, vault et Graphify : implementation reelle

Cette section decrit ce qui existe reellement dans ce depot (outillage sous
`scripts/`), pas une interface future. Voir aussi
`~/.claude/references/global-operational-rules.md` et
`.claude/skills/graphify/SKILL.md` pour les regles generales Graphify.

### Source de verite

1. `docs/decisions/DEC-XXXX-slug.md` — un ADR par decision, versionne Git.
   C'est la source canonique : titre, statut, dates, `supersedes`/
   `superseded_by`, entites Graphify deja validees.
2. `docs/DECISIONS.md` — index compact **genere**, ne jamais l'editer a la
   main (regenere a partir des ADR, ecrase toute edition manuelle).
3. Le vault AI-Memory (`projects/studio-os/decisions/`) est une projection
   enrichie et idempotente des ADR : contexte humain, prose curatee,
   annotations — jamais la source canonique.
4. PostgreSQL (table `decisions`) reste un miroir operationnel, pas la
   source canonique.

### Ajouter une decision

Creer directement `docs/decisions/DEC-XXXX-slug.md` (copier un ADR existant
comme modele : `id`, `title`, `status`, `source`, `sync_hash` au minimum).
Puis :

```
uv run python -m scripts.adr_index --root . --apply
uv run python -m scripts.vault_sync --root . --apply
```

Ne plus editer `docs/DECISIONS.md` a la main — c'est desormais un artefact
genere (`scripts/adr_index.py`).

### Regenerer l'index / controler l'integrite

```
uv run python -m scripts.adr_index --root . --check      # index a jour ?
uv run python -m scripts.vault_sync --root . --check      # vault synchronise ?
uv run python -m scripts.vault_lint --root .               # references valides ?
uv run python -m scripts.graphify_control --root .         # sequence complete (1-7)
```

`graphify_control` enchaine : validation des ADR, fraicheur de l'index,
statut de synchronisation vault, integrite des references Graphify,
construction du sous-graphe de decisions, comparaison du graphe composite
avant/apres, rapport de cout. Code de sortie non nul si une etape
obligatoire (1-4) echoue.

### Sous-graphe de decisions et graphe composite

`scripts/decision_graph.py` construit, sans aucun appel LLM, un noeud par
decision et des aretes typees (`documents`/`affects`/`implements`/
`constrains`/`supersedes`) vers les symboles de code references par
`graphify.entities`. Ce sous-graphe est ecrit dans un artefact separe
(`decisions_subgraph.json`) : le `graph.json` AST n'est jamais ouvert en
ecriture par cet outil, donc aucun risque de declencher la protection
anti-retrecissement de Graphify ni de perdre des noeuds. Un graphe
composite (`graph.composite.json`, optionnel via `--composite-out`) est la
simple union nodes/edges des deux, pour les requetes uniquement.

Une reference d'entite non resolue (`node_id` absent du graphe AST actuel,
ou `null`) est **refusee et rapportee**, jamais transformee en arete
inventee.

### Quand lancer une extraction semantique documentaire

Gouverne par `.graphify-update.toml` a la racine du depot (moteur :
`scripts/graphify_update_policy.py`, applique par le script partage
`~/.claude/scripts/graphify_incremental_update.py` — y compris pour les
fichiers passes explicitement via `--files`, la politique ne peut pas etre
contournee). Par defaut, un document est **refuse** sauf s'il correspond a
un motif de `[semantic.allowed]` (traite immediatement) ou de
`[semantic.milestone_only]` (traite uniquement avec `--milestone`, reserve
aux jalons d'architecture/release). `docs/DECISIONS.md` (genere) et les
copies de skills (`.claude/skills/graphify/`, `.agents/skills/graphify/`)
sont explicitement exclus — jamais extraits, meme via `--files`. Le code
natif suit toujours l'extracteur AST deterministe (0 token), independamment
de cette politique semantique.

### Lire le rapport de cout

`scripts/graphify_ledger.py` etend `cost.json` avec un journal par
tentative (`"attempts"`) — fichiers, backend, tokens, `tokens_status`
(`measured`/`unmeasured`, jamais 0 par defaut quand une mesure est
absente). Lecture retro-compatible avec l'ancien format (`"runs"` seul).

```
uv run python -m scripts.graphify_ledger --cost-json <graphify-out>\cost.json --by backend
uv run python -m scripts.graphify_ledger --cost-json <graphify-out>\cost.json --by file
uv run python -m scripts.graphify_ledger --cost-json <graphify-out>\cost.json --by ratio
uv run python -m scripts.graphify_ledger --cost-json <graphify-out>\cost.json --by top
```

### Resoudre une divergence depot/vault/base

- **Index perime** (`adr_index --check` echoue) : `adr_index --apply`.
- **Vault en retard** (`vault_sync --check` echoue) : `vault_sync --apply`.
  Un conflit signale (`status`/`supersedes`/`superseded_by` divergent entre
  l'ADR et le vault) n'est **jamais ecrase automatiquement** — resoudre a
  la main dans l'ADR ou le vault, puis relancer.
- **Reference Graphify cassee** (`vault_lint` en erreur) : alias `DEC-XXXX`
  duplique, entite `node_id: null` sans `unresolved: true`, ou
  `supersedes`/`superseded_by` pointant vers un `DEC-XXXX` inexistant —
  corriger la note ou l'ADR source, jamais l'ecraser silencieusement.
- **Table `decisions` Postgres en retard** : miroir operationnel seulement,
  pas bloquant pour un controle local ; a resynchroniser separement quand
  la base est disponible.

### Hooks Claude/Codex

Les deux hooks `PreToolUse` (`.claude/settings.json`, `.codex/hooks.json`)
doivent appeler `pwsh -NoProfile -File scripts/graphify-studio.ps1
hook-guard <search|read>` / `hook-check` — jamais `graphify.exe`
directement : le lanceur du depot definit `GRAPHIFY_OUT` avant d'invoquer
`hook-guard`/`hook-check`, sans quoi ce dernier ne trouve pas le graphe
centralise et reste silencieux (aucune erreur visible, juste aucune
orientation donnee a l'agent).
