# Inventaire câblage harnais — Library vs projection vs local (étapes 1-2)

Tâche Studio OS `ea20c54c-6594-48d7-8d7d-e1a8e9ed8b0`, étapes 1 et 2 : analyse seule, aucun code.
Références : `packages/studio-contracts/src/studio_contracts/library.py` (`HookContent`, `HookEvent`,
`HookMode`, `HookShell`), `packages/studio-client/src/studio_client/hook_sync.py`,
`docs/library/rebuild-2026/ARCHITECTURE.md`, `docs/library/roadmap-p0/P00-inventory.md`.
Conventions : `AGENTS.md` § projections (`.claude/`, `.codex/`, `.opencode/` = projections, jamais sources).

Légende : **N** = neutre / projetable (Core ou Project) · **P** = propre au poste (Personal ou local)
· **S** = secret (ne quitte jamais le poste, masqué ci-dessous) · **H** = technique harnais (ignoré du canonique).

## 0. Constats préalables (preuves)

- **`library_equivalence.py` absent.** `packages/studio-client/src/studio_client/library_equivalence.py`
  et `_EXCLUDED_PATHS` n'existent pas dans le worktree (recherche `equivalence|EXCLUDED` : seuls
  `EXCLUDED_DUPLICATE` de `library/packages/decisions*.json` et du rebuild-2026). La proposition §3
  s'ancre donc sur le contrat `HookContent` + `hook_sync.py` (merge préservant le non-géré,
  `merge_claude_hooks`) + `ARCHITECTURE.md` (table Core/Personal/Projet). Arbitrage **A3**.
- **`.opencode/opencode.json` absent.** `.opencode/` ne contient que `agents/` et `skills/`.
  Inventorié : `opencode.json` racine (3e fichier) ; la config utilisateur OpenCode
  (`~/.config/opencode/opencode.json`, gérée par `harness/opencode.py`) est hors dépôt. Arbitrage **A2**.
- **Connexe hors brief, minimal :** `.codex/hooks.json` (garde `PreToolUse`) est du câblage hook et
  conditionne la proposition Codex ; cité en §1 et §3, sans inventaire exhaustif.
- Secrets et chemins personnels masqués partout (`<masqué>`). Aucune valeur credential recopiée.

## 1. Inventaire champ par champ

### 1.1 `.claude/settings.json` (existe, 29 lignes)

| # | Champ | Valeur (expurgée) | Classe | Motif |
|---|---|---|---|---|
| 1 | `$schema` | URL schemastore | H | aide éditeur, non sémantique |
| 2 | `hooks.PreToolUse[0].matcher` | `Edit\|Write\|MultiEdit\|NotebookEdit` | N | motif d'outils, représentable `HookContent.matcher` (autorisé sur `pre_tool`) |
| 3 | `hooks.PreToolUse[0].hooks[0].type` | `command` | H | seul type supporté ; équivalent implicite d'une définition hook |
| 4 | `hooks.PreToolUse[0].hooks[0].command` | `pwsh -NoProfile -File "$CLAUDE_PROJECT_DIR/scripts/claude-hooks/protect-files.ps1"` | N (corps) + P (invocation) | le corps du script est projetable (`HookScript.body`, shell `pwsh`) ; l'enveloppe `pwsh -NoProfile -File` + `$CLAUDE_PROJECT_DIR` est une convention de poste/projection (`_SHELL_ARGV`, `_command` dans `hook_sync.py`) |
| 5 | `hooks.PreToolUse[0].hooks[0].timeout` | `15` | N | `timeout_seconds` (1–600) |
| 6 | `hooks.PostToolUse[0].matcher` | `Edit\|Write\|MultiEdit` | N | idem, `post_tool` |
| 7 | `hooks.PostToolUse[0].hooks[0].type` | `command` | H | idem |
| 8 | `hooks.PostToolUse[0].hooks[0].command` | `pwsh -NoProfile -File "$CLAUDE_PROJECT_DIR/scripts/claude-hooks/ruff-on-edit.ps1"` | N (corps) + P (invocation) | idem |
| 9 | `hooks.PostToolUse[0].hooks[0].timeout` | `60` | N | `timeout_seconds` |
| 10 | `mode` (bloquant vs informatif) | absent du fichier | N à trancher | `HookContent.mode` requis (`blocking`/`advisory`) ; non déductible du JSON. Arbitrage **A1** |

Corps `scripts/claude-hooks/protect-files.ps1` et `ruff-on-edit.ps1` : non lus (étape bornée aux 4 fichiers) ;
ils deviendraient `HookScript.body` après extraction + contrôle `contains_secret_material`. Arbitrage **A7**.

### 1.2 `.codex/config.toml` (existe, 20 lignes)

| # | Champ | Valeur (expurgée) | Classe | Motif |
|---|---|---|---|---|
| 11 | `[mcp_servers.studio-os].url` | URL MCP hébergée `<masqué: hôte distant>` | P | câblage machine ; ARCHITECTURE : Core exclut URLs locales/intégrations obligatoires |
| 12 | `[mcp_servers.studio-os].bearer_token_env_var` | nom de variable d'environnement (pas de valeur dans le fichier) | P | le **nom** est une convention de poste ; la valeur n'est dans aucun fichier (conforme) |
| 13 | `[mcp_servers.context7].url` | URL SaaS publique `<masqué: hôte distant>` | P | choix d'intégration du poste, même publique. Arbitrage **A5** |
| 14 | `[mcp_servers.postgres-test].command` | `uvx` | P | outil local de lancement |
| 15 | `[mcp_servers.postgres-test].args` | `--python 3.12 --with mcp<2 postgres-mcp --access-mode=restricted` | P | idem ; `--access-mode=restricted` reste une préférence locale, pas une règle Library |
| 16 | `[mcp_servers.postgres-test.env].DATABASE_URI` | `<masqué: credentials de test locales>` | S | secret (mot de passe + hôte/port) ; **reste local, jamais Library/projection** |

### 1.3 `opencode.json` racine (existe, 13 lignes)

| # | Champ | Valeur (expurgée) | Classe | Motif |
|---|---|---|---|---|
| 17 | `$schema` | URL opencode.ai | H | aide éditeur |
| 18 | `agent.explore.model` | `<masqué: référence de modèle du poste>` | P | référence runtime/modèle propre au poste → Personal au plus (ARCHITECTURE § Composition). Arbitrage **A6** |
| 19 | `agent.general.model` | `<masqué: référence de modèle du poste>` | P | idem |
| 20 | `mcp` | `{}` (objet vide) | — | rien à inventorier ; le MCP OpenCode utilisateur vit hors dépôt (`harness/opencode.py`) |

Note : `harness/opencode.py` précise qu'une entrée projet `opencode.json[c]` éclipserait la config
globale et est migrée — ce fichier racine (pins de modèles d'agents) est donc du câblage local,
pas une source Library.

### 1.4 `.opencode/opencode.json` (absent)

| # | Champ | Classe |
|---|---|---|
| 21 | fichier inexistant dans le worktree | — (voir **A2** : confirmer si le brief visait la config utilisateur hors dépôt) |

### 1.5 Connexe `.codex/hooks.json` (pour la proposition hook, minimal)

`hooks.PreToolUse[0]` : `matcher: Bash` (N, `HookContent.matcher` sur `pre_tool`),
commande inline `pwsh … "if (Test-Path …) { throw … }"` (corps N extractible en `HookScript.body`,
références `graphify-out` / `scripts/graphify-studio.ps1` relatives au dépôt → scope Project au plus),
pas de `timeout` (défaut harnais → 30 à l'import ; **A1**), `mode` à trancher (**A1**).
`hook_sync.py` ne projette pas vers Codex (`reports: codex:not_supported`) : ce hook resterait local
jusqu'à une évolution du projecteur (hors étapes 1-2).

## 2. Rattachement contrat (vérifié, sans extension requise)

- Vocabulaire fermé `HookEvent` (`library.py:861-875`) couvre `PreToolUse`/`PostToolUse`
  (`CLAUDE_EVENTS`, `hook_sync.py:42-52`) ; `OPENCODE_EVENTS` ne couvre que 4 événements
  (`pre_tool`, `post_tool`, `session_start`, `stop`) — nos deux hooks Claude sont exprimables côté OpenCode.
- `matcher` autorisé uniquement sur `pre_tool`/`post_tool` (`_HOOK_MATCHER_EVENTS`) : nos 3 cas OK.
- `mode bloquant` autorisé sur `pre_tool` (`_HOOK_BLOCKING_EVENTS`) : un `blocking` pour protect-files
  est valide ; côté OpenCode le bloquant n'est exprimable que sur `pre_tool` (`_OPENCODE_BLOCKING_EVENTS`).
- `timeout` 15/60 ∈ [1, 600] ✓ ; shell `pwsh` ∈ `HookShell` ✓ ; `extra="forbid"` (`common.py:11`) :
  `$schema`, `type: command`, noms de variables d'env n'ont aucun champ cible — confirmation qu'ils
  restent hors Library.
- `hook_sync.merge_claude_hooks` remplace uniquement les groupes gérés (commandes tracées au manifeste)
  et préserve le non-géré : équivalent fonctionnel du `_EXCLUDED_PATHS` cité par le brief (préservation
  explicite du local, `ARCHITECTURE.md` principe 5).

## 3. Proposition : Library vs projection vs local

| Source (champ) | Devenir proposé | Détail |
|---|---|---|
| `PreToolUse` protect-files (matcher, timeout 15, corps script) | **Définition Library** `kind: hook` | `event: pre_tool`, `matcher: Edit\|Write\|MultiEdit\|NotebookEdit`, `timeout_seconds: 15`, `scripts: [{shell: pwsh, body: <extrait de protect-files.ps1>}]`, `mode: <A1>` ; scope Project (script relatif au dépôt) |
| `PostToolUse` ruff-on-edit (matcher, timeout 60, corps script) | **Définition Library** `kind: hook` | `event: post_tool`, `matcher: Edit\|Write\|MultiEdit`, `timeout_seconds: 60`, `mode: advisory <A1>` |
| `.codex/hooks.json` garde graphify-out | **Définition Library** `kind: hook` **ou reste local** | importable (`pre_tool`/`Bash`/timeout 30 par défaut) mais **non projetable vers Codex** aujourd'hui ; à défaut d'évolution du projecteur, reste local. **A8** |
| `.claude/settings.json` fusionné | **Projection générée** | `hook_sync` (`_plan_claude_settings`, manifest `.studio-os/library-hooks-manifest.json`, consentement par empreinte) ; groupes non gérés préservés |
| plugin OpenCode | **Projection générée** | `render_opencode_plugin` (déjà couvert par `hook_sync`) |
| `type: command`, `$schema`, enveloppe `pwsh -NoProfile -File` + `$CLAUDE_PROJECT_DIR` | **Projection générée** (détail d'adapter) | jamais stockés ; reconstruits par `_SHELL_ARGV`/`_command` |
| URLs MCP, `bearer_token_env_var`, `command/args` uvx, `DATABASE_URI` | **Reste local** | câblage machine/poste ; `DATABASE_URI` secret |
| pins `agent.*.model` (`opencode.json`) | **Reste local** (Personal au plus) | référence de modèle du poste ; éventuel `model_profile` Library distinct, jamais inline. **A6** |
| `context7` (URL publique) | **Reste local** par défaut | activation = préférence de poste. **A5** |

**Extensions de contrat : aucune requise.** Tous les champs N tiennent dans `studio.library.hook/v1`
sans ajout (cf. §2) ; toute évolution future serait additive (nouveau champ optionnel ou valeur
d'enum), jamais un renommage — principe à faire valider si un besoin émerge (**A4** : aucun besoin
identifié dans ces 4 fichiers).

## 4. Arbitrages à faire valider par l'humain (pas de DEC créée)

- **A1 — `mode` des 3 hooks** : `blocking` pour protect-files (et garde graphify-out, qui `throw`) ?
  `advisory` pour ruff-on-edit ? `timeout` par défaut (30) pour la garde Codex sans timeout ?
- **A2 — `.opencode/opencode.json`** : le brief visait-il un fichier qui n'existe pas, ou la config
  utilisateur hors dépôt (`harness/opencode.py`) ? Confirmer que « absent » clôt le point.
- **A3 — `library_equivalence.py` / `_EXCLUDED_PATHS`** : module inexistant ; renommé, déplacé ou
  à créer ? En attendant, `merge_claude_hooks` + manifeste font foi (§2).
- **A4 — extensions additives** : confirmer « aucune » pour ce périmètre ; toute future extension reste
  additive et versionnée (`content_schema`).
- **A5 — `context7`** : Personal/partagé ou exclu (intégration non obligatoire, même publique) ?
- **A6 — pins de modèles `opencode.json`** : local pur ou `model_profile` Personal ? (Jamais Core :
  modèle privé exclu du Core par ARCHITECTURE.)
- **A7 — extraction des corps `.ps1`** : qui extrait/sanitize les 2 scripts vers `HookScript.body`
  (étape ultérieure), avec contrôle `SECRET_MATERIAL` ?
- **A8 — Codex** : la garde `hooks.json` devient-elle une définition Library non projetée (rapport
  `codex:not_supported`, reste local en pratique) ou attend-on un projecteur Codex (code, hors étapes 1-2) ?
