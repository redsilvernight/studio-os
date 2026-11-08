# P00 — Inventaire `.agents/` et projections face aux kinds du Library

Spike en lecture seule. Date : 2026-11-08. Worktree `library-p0-spikes`. Aucune commande de test lancée : les constats viennent de la lecture des sources citées.

## 1. Périmètre réel

| Source canonique | Contenu (lu) | Projections (lues) |
|---|---|---|
| `.agents/definitions/*.md` | 6 agents : contract-guardian, dashboard-a11y, migration-reviewer, studio-architect, studio-tester, sync-debugger | `.claude/agents/<k>.md`, `.opencode/agents/<k>.md`, `.codex/agents/<k>.toml` (6 chacun) |
| `.agents/rules/*.md` | 8 fichiers : 7 règles avec `applies_to` + `studio-protocol.md` (sans frontmatter) | `.claude/rules/<k>.md` (7, enveloppe `paths:`) ; bloc généré `<!-- BEGIN GENERATED RULES -->` d'`AGENTS.md` (liens + globs, pas le corps) ; `@.agents/rules/studio-protocol.md` importé par `CLAUDE.md` |
| `.agents/skills/*/SKILL.md` | 9 skills (+ `references/` pour `graphify` et `studio-task`) | `.claude/skills` : 7 ; `.codex/skills` et `.opencode/skills` : 3 (studio-task/context/handoff) |

Kinds Library (`packages/studio-contracts/src/studio_contracts/library.py`, `LibraryKind`) : `rule`, `skill`, `agent_definition`, `model_profile`, `workflow`, `hook`. Les trois kinds « fichiers » du client (`SkillLibraryKind` dans `packages/studio-contracts/src/studio_contracts/local/skills.py`, `EntryKind` dans `dashboard/src/skillsSync.ts`, `PUBLISH_KINDS` dans `packages/studio-client/src/studio_client/publish.py`) sont `skill`, `rule`, `agent`. Hors `.agents/` : `.claude/settings.json` (hooks PreToolUse/PostToolUse vers `scripts/claude-hooks/*.ps1`), `.codex/hooks.json`, `.codex/config.toml` (MCP), `.claude/launch.json` : candidats au kind `hook`, aucun ne passe par `.agents/`.

Schémas de contenu Library (tous `extra="forbid"`, `common.py`) :
- `RuleContent` : `content_schema`, `text`.
- `SkillContent` : `content_schema`, `text`, `files[]` (path, text, sha256 ; 64 fichiers max, 512 Kio au total).
- `AgentDefinitionContent` : `content_schema`, `summary`, `intended_use`. Rien d'autre. Pas de corps d'instructions, pas de `tools`, `triggers`, `edit_policy`.
- Liens : `DependencyPin` épinglé par version (`_BINDING_MATRIX` : agent→rule `applies_rule`, agent→skill `uses_skill`, agent→model_profile `requires_model_profile`, etc.). Les exigences d'un agent passent par un `model_profile` lié, pas par un champ inline.

## 2. (a) Tableau champ par champ

Légende : OK = représentable aujourd'hui ; V2 = nécessite agent schema v2 (ou extension de kind) ; HARNAIS = propre à un harnais, ne doit pas entrer dans le canonique.

### Agents (`.agents/definitions/*.md`, parsés par `CanonicalAgent` dans `packages/studio-client/src/studio_client/canonical.py`)

| Champ | Exemple | Classe | Où / pourquoi |
|---|---|---|---|
| `stable_key` | `studio-tester` | OK | `LibraryResource.stable_key` |
| `title` | `Studio Tester` | OK | titre de la ressource (`to_publish_payload` → `PublishItem.title`) |
| `summary` | texte | OK | `AgentDefinitionContent.summary` |
| `intended_use` | texte | OK | `AgentDefinitionContent.intended_use` |
| corps Markdown (cycle commun + rôle) | ~50 lignes | V2 | aucun champ `instructions` dans le contrat. `publish.py` l'ignore ; `scripts/library_import.py::_content` le glisse dans `intended_use` (détournement de champ). |
| `triggers` (liste) | « after implementing a feature » | V2 | lu par `render_shared_body` dans `adapters/base.py` (`content["triggers"]`) mais interdit par `extra="forbid"` |
| `edit_policy` (`deny`/`ask`) | `deny` | V2 | consommé par les 3 adapters (`ensure_supported`, `permission.edit` d'OpenCode) ; absent du contrat. Sémantique neutre : à garder canonique. |
| `tools` (`read, grep, glob, bash, powershell`) | liste | V2 | adapters `claude.py` (`TOOL_DISPLAY_NAMES`) ; vocabulaire de besoins abstraits. Ressemble à `CapabilityRequirement.tools_required` mais ce champ vit dans `model_profile`, pas dans l'agent. |
| `requirements.reasoning` | `medium`/`high` | OK (indirect) | `CapabilityRequirement.reasoning` via un `model_profile` épinglé. Il faut créer et lier un profil ; l'import actuel ne le fait pas (non vérifié : `build_publish_items` ne produit aucun pin vers un `model_profile`). |
| `rules: [...]` | `[contracts, python-conventions]` | OK | pins `applies_rule` ; `publish.py` les résout en pins de versions actives |
| `skills: [...]` | `[graphify]` | OK | pins `uses_skill` |
| (interdits : `model`, `provider`, `harness`) | | n/a | rejetés par `load_definition` ; cohérent avec le contrat |

### Rules (`.agents/rules/*.md`)

| Champ | Classe | Où / pourquoi |
|---|---|---|
| `stable_key` (= nom de fichier) | OK | clé de ressource |
| `name` | OK (redondant) | non stocké ; égal à `stable_key` |
| corps Markdown | OK | `RuleContent.text` (≤ 65 536 car.) |
| `applies_to` (globs) | V2 | aucun champ dans `RuleContent`. Perte réelle : sert à générer `.claude/rules/*` (`paths:`) et la liste d'`AGENTS.md` (`render_agents_rules_block`). Le client relit `applies_to` depuis les fichiers (`load_rule_meta`), jamais depuis le Library. |
| enveloppe `paths:` | HARNAIS | `.claude/rules/<k>.md` : `render_claude_rule` |
| `studio-protocol.md` (sans frontmatter) | HARNAIS | texte de bootstrap, exclu volontairement (`canonical_rule_keys`) ; importé par `@` dans `CLAUDE.md` |
| bloc `GENERATED RULES` d'`AGENTS.md`, bloc `STUDIO-OS MANAGED` de `CLAUDE.md` | HARNAIS | projections par marqueurs (`merge_agents_rules`, `render_claude_md_block`) |

### Skills (`.agents/skills/<k>/SKILL.md`)

| Champ | Classe | Où / pourquoi |
|---|---|---|
| nom du dossier = `stable_key` | OK | clé (pattern `SkillStableKey`) |
| `name` (frontmatter) | OK (redondant) | reconstruit depuis `stable_key` par `render_skill` (`skill_sync.py`) |
| `description` | OK (partiel) | pas de champ ; utilisée comme **titre** de la ressource (`_skill_title`, `library_import._content`) puis relue comme `description` de la projection (`LibraryContextItem.description`, non vérifié en détail) |
| `disable-model-invocation` (ex. `alembic-migration`) | HARNAIS (Claude Code) | absent de `SkillContent` ; `render_skill` régénère un frontmatter à 2 clés seulement |
| corps Markdown | OK | `SkillContent.text` |
| `references/*.md` (`studio-task`, `graphify`) | OK (si `files[]` utilisé) | `SkillContent.files` existe, mais `publish.py::build_publish_items` n'envoie que `text` ; seul `scripts/library_import.py` gère `files` (non vérifié sur un cas réel) |
| autres frontmatter vendeur (`allowed-tools`, `model`…) | HARNAIS | absents du dépôt aujourd'hui ; aucun champ prévu |

### Projections par harnais (cibles, jamais sources)

| Cible | Format | Champs produits (lu) |
|---|---|---|
| `.claude/agents/<k>.md` | frontmatter `name`, `description`, `model`?, `tools` + corps | `adapters/claude.py` |
| `.opencode/agents/<k>.md` | `description`, `mode: subagent`, `model`?, `permission.edit` | `adapters/opencode.py` |
| `.codex/agents/<k>.toml` | `name`, `description`, `model`?, `model_reasoning_effort`, `developer_instructions` | `adapters/codex.py` |
| `.claude/skills`, `.codex/skills`, `.opencode/skills` | copie verbatim de `SKILL.md` (3 skills workflow pour codex/opencode) | `workflow_skill_projections` ; `skill_sync.py` pour l'installation dashboard (cibles `agents`/`claude`, section OpenCode) |
| `.claude/settings.json`, `.codex/hooks.json`, `.codex/config.toml` | hooks / MCP | HARNAIS, sans source `.agents/` ; kind `hook` possible (`HookContent`, non relu ici) |

## 3. (b) Pertes d'un import « tel quel » (`publish.py` / `library_import.py`)

1. **Corps des agents perdu** (publish) ou **stocké dans `intended_use`** (import de packages). Le Library ne sait pas régénérer `.claude/agents/*` fidèlement. `merge`/`build_merged_resolved` comble en prenant les clés « fichier seulement » (`instructions`, `triggers`, `edit_policy`, `tools`) dans le dépôt : sans dépôt, ces champs sont défaut (commentaire dans `canonical.py`, ~l.383).
2. **`edit_policy` perdue** : un agent en lecture seule (`deny`) redevient potentiellement éditeur dans une projection issue du seul Library. Risque de sécurité, pas seulement cosmétique.
3. **`tools` et `triggers` perdus** : allowlist Claude Code vide, section « Triggers » absente.
4. **`requirements` perdus** : aucun `model_profile` ni pin créé ; `model_reasoning_effort` Codex retombe sur le défaut.
5. **`applies_to` des rules perdu** : plus de `paths:` Claude, plus de liste de globs dans `AGENTS.md`. Les règles deviennent globales ou invisibles.
6. **Frontmatter de skill réduit à `name`/`description`** : `disable-model-invocation` perdu (`alembic-migration` redeviendrait invocable par le modèle).
7. **`references/` des skills** : perdues par `publish.py` ; conservées seulement par `library_import.py` (`files[]`). Les projections `.claude/skills/studio-task/` et `.codex/skills/studio-task/` n'ont déjà que `SKILL.md` (lu) : `references/completion.md` et `roles.md` n'y sont pas copiés.
8. **Ensembles incomplets** : `graphify` et `studio-decision` n'ont pas de projection `.claude/`, `.codex/` ni `.opencode/` (lu). Intentionnel ou non : non vérifié.
9. **Hors Library** : `studio-protocol.md`, blocs marqueurs d'`AGENTS.md` et `CLAUDE.md`, hooks et MCP des harnais. Aucun import ne les couvre.
10. **Identité** : `title` d'un skill = `description` (long, une phrase) ; `title` d'une rule = `stable_key`. Comparaisons et diffs dashboard sur le titre peu fiables.
11. **Pins** : `publish.py` épingle la version active au moment de l'import, sans relation explicite ; un agent importé avant ses skills échoue (d'où l'ordre rules → skills → agents).

## 4. (c) Recommandations

### P31 — schéma agent v2 (`studio.library.agent_definition/v2`)

- Ajouter, en `extra="forbid"`, uniquement des champs neutres vis-à-vis du harnais : `instructions` (texte, plafond comme `RULE_SKILL_TEXT_MAX_LENGTH`), `triggers: list[str]`, `edit_policy: Literal["deny","ask","allow"]`, `tools: list[str]` (vocabulaire de besoins : `read`, `grep`, `glob`, `bash`, `powershell`).
- Garder `requirements` hors de l'agent : un `model_profile` épinglé (décision P3/DEC-0066 déjà dans le docstring). Prévoir côté import la création du profil à partir de `requirements.reasoning`.
- v1 reste lisible (champs absents = défauts actuels de `canonical.py`) ; migration additive, comme `SkillContent.files`. Faire tourner `adapters_check` sur les 6 agents avant et après : la sortie des trois adapters doit être identique à l'actuelle (octet près).
- Ne pas stocker `mode`, `permission`, `model_reasoning_effort`, `developer_instructions` : ce sont des sorties d'adapters (HARNAIS).
- Décision liée à confirmer : `edit_policy: allow` est-il utile, ou garde-t-on le tri-état implicite actuel (`deny` par défaut) ?

### Hors P31 mais bloquant pour P43

- Rule v2 : champ `applies_to: list[str]` (additif). Sans lui, l'import de règles est dégradé (perte 5).
- Skill : choisir où vivent `disable-model-invocation` et la `description`. Proposition minimale : `description` dédiée (additif), le flag Claude reste en métadonnée de projection, pas dans le canonique.

### P43 — import

- Source unique : `.agents/` (jamais les projections). Réutiliser `canonical.py` et `publish.py` ; unifier avec `scripts/library_import.py` pour qu'un seul chemin gère `files[]` et le corps d'agent (supprimer le détournement dans `intended_use`).
- Importer dans cet ordre : rules, skills (avec `files[]` = `references/`), `model_profile`s dérivés, agents v2 avec pins.
- Exclure explicitement et logger : `studio-protocol.md`, blocs `AGENTS.md`/`CLAUDE.md`, hooks et MCP des harnais, projections `.claude/.codex/.opencode`. Kind `hook` : import séparé à décider.
- Test de non-perte : round-trip `.agents/` → Library → adapters, comparé aux fichiers committés (`.claude/agents`, `.opencode/agents`, `.codex/agents`, `.claude/rules`). Tout écart = perte listée en (b).
- Signaler les skills sans projection (perte 8) avant import plutôt que les ignorer.

## 5. Non vérifié

- Contenu complet de `HookContent` et correspondance exacte avec `.claude/settings.json` (lu en partie seulement).
- Comportement serveur de `services/api/src/studio_api/services/library.py` (validation à la création de version, 933 lignes, non lu).
- `LibraryContextItem.description` et la chaîne de rendu des skills côté daemon (`daemon/skills_bridge.py`) : non lus.
- Corps complets des 8 rules et 9 skills : seul le frontmatter a été énuméré (clés comptées par script).
- Rendu réel des projections vs sources (aucun `studio-client adapters check` exécuté).
- Existence de définitions Library déjà publiées en base (état Studio OS non consulté).
