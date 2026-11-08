# P30 — Contenu d'un agent v2 (spike de décision)

Statut : proposition, aucun code ni projection modifié. Base : worktree `lib-p30` (depuis `dev`).
Sources lues : `packages/studio-contracts/.../library.py` (`AgentDefinitionContent`), `packages/studio-client/.../canonical.py` (`CanonicalAgent`, `_resolved_agent_head`, `to_publish_payload`), `adapters/{base,claude,codex,opencode}.py`, `scripts/library_import.py` (`_content`), `scripts/library_packages.py`, `library/studio/agents/*.md` (9), `.agents/definitions/*.md` (6), projections `.claude/agents`, `.codex/agents`, `.opencode/agents`, `docs/library/roadmap-p0/P00-inventory.md` (reco P31).

## 1. Inventaire

| Couche | Champs |
|---|---|
| Schéma Library v1 (`extra="forbid"`) | `content_schema`, `summary`, `intended_use` |
| Définition canonique `.agents/definitions/*.md` | frontmatter : `stable_key`, `title`, `summary`, `intended_use`, `triggers`, `edit_policy`, `tools`, `requirements.reasoning`, `rules`, `skills` ; corps = instructions. `model`/`provider`/`harness` rejetés par `load_definition`. |
| Tête résolue côté client (`_resolved_agent_head`) | v1 + `instructions`, `triggers`, `edit_policy`, `tools` (« file-only », jamais publiés) |
| Import `library/studio/agents/*.md` | frontmatter : `kind`, `stable_key`, `scope`, `summary`, `model_profile` (lien, pas contenu) ; corps stocké dans `intended_use` (écart : le corps entier est stocké comme « intended_use », `title = stable_key`) |
| Manifest de paquet | `tier`, `compatibility`, `owner`, `visibility`, `requires_consent`, `status`, `supersedes`, `version` : métadonnées de paquet, pas de contenu |
| Projection Claude Code | `name`, `description`, `model`, `tools` (labels `Read`, `Grep`…) |
| Projection Codex | `name`, `description`, `model`, `model_reasoning_effort`, `developer_instructions` |
| Projection OpenCode | `description`, `mode: subagent`, `model`, `permission.edit` |

Constats : (1) les 6 agents projetés ont tous `edit_policy: deny` et les mêmes `tools`, `reasoning` medium (high pour `studio-architect`) ; (2) `instructions`, `triggers`, `edit_policy`, `tools` existent déjà dans le modèle client mais sont perdus à la publication ; (3) les 9 agents `library/studio` n'ont ni `triggers`, ni `edit_policy`, ni `tools` ; (4) aucun test de `tests/library_rebuild` ne fige la forme du contenu agent (seuls l'import par `kind` et les helpers d'install y touchent) ; la forme est figée par `tests/api/test_library*.py`, `tests/client/adapters/test_adapters_p10.py`, `dashboard/src/views/library*.test.ts`.

## 2. Décision champ par champ

Principe : le contenu canonique décrit ce que l'agent est, sait faire et n'a pas le droit de faire, en termes neutres. Tout nom, format ou valeur propre à un harnais est calculé par une projection.

| Champ | Où aujourd'hui | Décision | Motif |
|---|---|---|---|
| `content_schema` | v1 | Garder (`.../v2`) | Discriminant de version. |
| `summary` | v1, tous | Garder | Une phrase ; source unique de `description` des projections. |
| `intended_use` | v1, canonique | Garder (court, optionnel) | Quand l'utiliser. Ne plus y mettre le corps (corriger l'import). |
| `instructions` | corps `.md`, tête client | Déplacer dans le contenu v2 | Prose de l'agent : sans elle la Library ne porte pas l'agent. Plafond comme `RULE_SKILL_TEXT_MAX_LENGTH`. |
| `triggers` | canonique, tête client | Déplacer dans v2 | Neutre ; rendu par les adapters. |
| `edit_policy` | canonique, tête client | Déplacer dans v2, `Literal["deny","ask","allow"]` | Neutre ; les adapters le traduisent (`permission.edit`, avertissement). |
| `tools` | canonique, tête client | Déplacer dans v2, besoins neutres (`read`, `grep`, `glob`, `bash`, `powershell`, vocabulaire ouvert validé par motif) | Neutre ; Claude mappe vers `Read`…, les autres avertissent. |
| `title` | canonique | Garder au niveau ressource (pas dans `content`) | Existe déjà (`resource.title`) ; l'import doit le renseigner depuis le fichier au lieu de `stable_key`. |
| `stable_key` | canonique | Garder au niveau ressource | Identité, déjà hors contenu. |
| `rules`, `skills` | canonique | Retirer du contenu ; liens versionnés `library_resource_links` | Déjà le cas (`to_publish_payload`) ; une seule source de vérité. |
| `requirements.reasoning` | canonique | Retirer ; devient un `model_profile` lié | DEC-0066 : exigences uniquement via profil épinglé. |
| `model_profile` (frontmatter import) | `library/studio` | Retirer du contenu ; lien | Idem. |
| `model`, `provider`, `harness`, `model_ref` | rejetés | Rester interdits | Concret = bindings (P4) / adapters. |
| `name` | projections | Retirer (dérivé de `stable_key`) | Sortie d'adapter. |
| `description` (Claude/Codex/OpenCode) | projections | Retirer (dérivé de `summary`, tronqué à 300) | Sortie d'adapter. |
| `mode` (OpenCode) | projection | Retirer | Spécifique harnais. |
| `permission.edit` (OpenCode) | projection | Retirer (dérivé de `edit_policy`) | Spécifique harnais. |
| `model_reasoning_effort` (Codex) | projection | Retirer (dérivé du profil) | Spécifique harnais. |
| `developer_instructions` (Codex) | projection | Retirer (dérivé de `instructions`) | Spécifique harnais. |
| `tools` en labels Claude (`Read`…) | projection | Retirer | Spécifique harnais. |
| `kind`, `scope` (frontmatter import) | `library/studio` | Hors contenu | Métadonnées de ressource/paquet. |
| `tier`, `compatibility`, `owner`, `visibility`, `requires_consent`, `status`, `supersedes` | manifest | Hors contenu | Métadonnées de paquet. |

## 3. Schéma v2 proposé

```python
class AgentDefinitionContentV2(ContractModel):          # extra="forbid"
    content_schema: Literal["studio.library.agent_definition/v2"]
    summary: str | None = None
    intended_use: str | None = None
    instructions: str | None = Field(default=None, max_length=RULE_SKILL_TEXT_MAX_LENGTH)
    triggers: list[str] = []
    edit_policy: Literal["deny", "ask", "allow"] | None = None
    tools: list[str] = []          # besoins neutres, pas une allowlist harnais
```

Dans la table des contenus : union discriminée sur `content_schema` (v1 | v2). Pas de champ `harness_overrides` : les spécificités harnais vivent dans des projections (adapters aujourd'hui ; un éventuel fichier d'override par harnais hors canonique si le besoin apparaît, cf. questions).

## 4. Impact

- Migration : additive. v1 reste lisible (champs absents = défauts de `canonical.py`). Pas de réécriture des versions existantes ; la v2 naît à la prochaine version publiée. Aucune migration Alembic (contenu JSON).
- Import (`library_import._content`) : `.agents/definitions` : corps vers `instructions`, `intended_use` depuis le frontmatter, `triggers`/`edit_policy`/`tools` copiés, `title` du fichier ; `requirements.reasoning` vers création/épinglage d'un `model_profile`, `rules`/`skills` vers liens. `library/studio/agents` : corps vers `instructions` (plus `intended_use`), `model_profile` inchangé.
- Client : `to_publish_payload` publie les champs v2 ; `_resolved_agent_head` n'a plus de clés « file-only » ; `CanonicalAgent.requirements` dérivé du profil épinglé.
- Projection : sortie des 3 adapters inchangée octet pour octet sur les 6 agents (critère : `studio-client adapters check` avant/après). Les adapters lisent déjà `content_map`.
- Autres consommateurs : `skills_bridge.py`, dashboard (`library.test.ts`, `libraryForms.test.ts`, `p13.spec.ts`), `dashboard/openapi.json` + `openapi-schema.ts` (skill `openapi-sync`), `tests/api/test_library*.py`, `test_p13_e2e`, `tests/client/adapters/test_adapters_p10.py`.
- Hors périmètre de ce spike : implémentation (P31), import de masse (P43).

## 5. Questions ouvertes

1. `edit_policy` : garder `allow` et `None` distincts ? Le loader fichier défaut à `deny` (sûr) ; la Library doit-elle toujours stocker la valeur explicite ?
2. `tools` (besoin de l'agent) vs `CapabilityRequirement.tools_required` (exigence runtime du profil) : recouvrement. Fusionner dans le profil ou garder deux notions ?
3. `requirements` : un profil par agent ou profils partagés par niveau (`reasoning-medium`) ? Impact sur les liens et le dashboard.
4. Plafond de `instructions` : même borne que rules/skills, ou plus haute (certains agents `library/studio` font 5-7 Ko) ?
5. Overrides harnais éventuels (ex. flag Claude sans équivalent) : projections seules ou fichier d'override versionné hors canonique ?
6. Agents `library/studio` sans `edit_policy`/`tools` : laisser vides ou renseigner à l'import ?
7. Titre : l'import met `title = stable_key` ; aligner sur le `title` canonique ou normaliser côté Library (cf. constat 10 de P00) ?
