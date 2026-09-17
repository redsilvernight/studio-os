---
id: DEC-0074
title: 'P10 Adapters locaux : meme definition canonique vers Claude Code et OpenCode, core neutre'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0074 — P10 Adapters locaux : même définition canonique vers Claude Code et OpenCode, core neutre

Ferme le gate P10 (« même définition traduite vers plusieurs harnesses ») :
`packages/studio-client/src/studio_client/adapters/` projette une
`ResolvedAgentDefinition` P5 (éventuellement accompagnée d'un Context
Package P9 générique) vers deux artefacts harness via deux adapters
indépendants consommant exactement le même type canonique d'entrée.
Claude Code d'abord (abstraction validée), OpenCode ensuite (preuve que
l'abstraction n'était pas spécifique à Claude).

## 1. Boundary locale

```text
ResolvedAgentDefinition (+ ContextPackage générique optionnel)
  → studio_client.adapters (Bloc B uniquement)
  → ClaudeCodeAdapter  → .claude/agents/<key>.md
  → OpenCodeAdapter    → .opencode/agents/<key>.md
```

Aucun endpoint VPS (`POST /adapt/...` refusé), aucun outil MCP
(`studio_translate_to_*` refusé), aucun service serveur de traduction.
Le VPS expose du canonique (P7 `POST /resolutions`, déjà existant) ;
le client local traduit. Aucun `ClaudeAgentDefinition` intermédiaire :
les deux adapters lisent le même objet canonique, jamais l'un via l'autre.

## 2. Contrat canonique d'entrée

`ResolvedAgentDefinition` (`studio_contracts/resolution.py`, DEC-0069) :
agent + rules + skills + model_profile 0..1 + requirements exactes +
références préservées + runtime sélectionné + provenance. Harness-neutral
par construction (aucune branche produit dans le core, §8).

Relation P5 : l'adapter consomme `resolve_agent`/`resolve_full` tel quel ;
`resolve_agent` et `select_runtime` restent intacts (suite P5 verte,
aucune donnée ajoutée au core pour « aider » un harness).
Relation P9 : le Context Package voyage en option générique
(`context: ContextPackage | None`) et se projette en section
récapitulative ; le composeur (`studio_client/context/`) est inchangé
(suite P9 verte), jamais de `ClaudeContextPackage`.

## 3. Contrat adapter générique (référence locale, pas norme partagée)

`adapters/base.py` : `Adapter` (protocole minimal `translate` pur),
`AdapterResult` (artefacts + warnings + métadonnées non normatives),
`AdapterError` (`invalid_canonical`/`harness_mismatch`/`unsupported`/
`materialization_failed`), `AdapterArtifact` (chemin relatif + contenu +
sha256), registry local `adapter_id → implémentation` (chaînes ouvertes,
`get_adapter`/`register_adapter`/`list_adapters`), `sanitize_agent_filename`,
`render_shared_body` (corps canonique unique partagé par les deux harnesses),
`materialize` (écriture sûre). Traduction pure : pas de résolution, pas de
sélection runtime, pas de réseau, pas de subprocess, pas d'exécution LLM.

## 4. Formats cibles (observés, non normatifs)

Formats relevés dans le repo lui-même, jamais depuis mémoire :
Claude Code `.claude/agents/*.md` = frontmatter
`name`/`description`/`model?` + corps Markdown ;
OpenCode `.opencode/agents/*.md` = frontmatter
`description`/`mode`/`model?` + corps Markdown.
La documentation produit externe n'est pas devenue norme Studi'OS ;
si un format harness évolue, seul son adapter change.

## 5. Mapping (implémentation réelle)

```text
CANONICAL                          | CLAUDE CODE              | OPENCODE                 | LOSSLESS | NOTES
AgentDefinition (titre/summary)    | name + description + #   | description + #          | ~oui     | description repliée 1 ligne (corps garde l'intégral)
Rule (RuleContent.text)            | section ### rule         | section ### rule         | oui      | ordre canonique préservé, jamais un Skill
Skill (SkillContent.text)          | section ### skill        | section ### skill        | oui      | jamais modifié pour le harness
ModelProfile (requirements)        | section Model req.       | section Model req.       | oui      | requirements seules ; aucun modèle inventé
runtime harness/provider/model     | section Runtime + model? | section Runtime + model? | partiel  | model projeté seulement si runtime concret ; jamais re-sélectionné
Context Package                    | section Context          | section Context          | résumé   | récapitulatif générique, payloads non réécrits
provenance                         | section Provenance       | section Provenance       | oui      | données, jamais de phrases
composed_agents / workflows        | warning, non expansé     | warning, non expansé     | non      | refs préservées (workflows : P11)
tools_required                     | section descriptive      | section descriptive      | non      | aucun allowlist harness inventé (warning)
permissions harness                | n/a                      | omis (défauts harness)   | non      | warning permissions_defaulted
```

## 6. Runtime / Harness / Provider / Model

Quatre concepts disjoints (DEC-0070) : la traduction ne déduit jamais
l'adapter de `provider_ref` ni de `model_ref` (testé : toute combinaison
provider/modèle se traduit sous les deux adapters ; un `model_ref`
contenant « claude » sous l'adapter opencode reste de l'opencode).
`harness_ref` présent et différent de l'adapter demandé = `AdapterError
(harness_mismatch)` explicite, canonique intact, jamais de bascule
silencieuse. `harness_ref` absent = traduction générique vers les deux.
`RuntimeCapabilities` servent à la compatibilité P5/P6, jamais au dispatch.

## 7. Traduction vs matérialisation

`translate` = artefact en mémoire, pur, déterministe
(`translate(X) == translate(X)`, sha256 par artefact).
`materialize(result, root, overwrite=False)` = effet de bord séparé :
validation complète d'abord (chemins relatifs POSIX, confinement sous
`root` + dossier géré, refus d'écraser sans `overwrite`), écriture
temp+replace ensuite, jamais de suppression hors set, fichiers utilisateur
non gérés intacts (testé). Erreur à mi-chemin = `AdapterError`, jamais un
résultat semi-valide ; le canonique, traité en lecture seule, est vérifié
inchangé y compris après exception.

## 8. Sécurité filesystem et secrets

`sanitize_agent_filename` borne le `stable_key` à `[A-Za-z0-9-_]` (aucun
traversal, aucun absolu) ; `materialize` re-valide par `resolve()` +
`relative_to`. Aucun secret n'est projeté par construction : seules les
refs ouvertes et les textes canoniques voyagent (`runtime_metadata`
inexistant sur `RuntimeTarget`, jamais sérialisé ; test dédié).
La prose utilisateur (rules/skills) transite verbatim — l'adapter ne la
censure ni ne l'enrichit.

## 9. CLI locale générique

`studio-client adapters list` (ids + dossiers gérés, sans réseau) et
`studio-client adapters export --adapter <open-ref> --stable-key <key>
[--project-id] [--out-dir] [--overwrite] [--with-context] [--json]`.
Le dispatch reste dans la couche locale ; `--adapter` est une chaîne
ouverte (pas d'enum fermé). `StudioApiClient.resolve_agent`
(`POST /api/v1/resolutions`, lecture pure retryable) est la seule méthode
ajoutée — additive, alignée P7, aucun contrat partagé modifié.

## 10. Non-objectifs respectés

Aucune exécution Claude Code/OpenCode, aucun subprocess, aucun prompt,
aucun scheduler, aucune discovery provider/modèle, aucun catalogue vendor,
aucune auto-sélection, aucun Context Composer spécifique harness, aucune
persistance serveur. P6 inchangé (aucune colonne `claude_code_...`),
P9 inchangé, P5 inchangé, P7/P8 inchangés.

## 11. Durcissement contractuel

Aucun contrat partagé touché (`studio_contracts` intact, aucune route,
aucun outil MCP, aucune migration) → workflow `contract-change`
non requis (audit §56 : surface strictement client-locale additive) ;
`contract-guardian` passé en revue indépendante : APPROVE, aucune réserve
bloquante (absence de contamination du canonique vérifiée, aucun branching
produit dans le core, frontières P7/P8/P9 intactes, `resolve_agent`
consommateur pur de la surface P7 existante). Test garde-fou permanent : `test_core_stays_free_of_
harness_provider_branches` balaie contrats + services Library/résolution/
bindings/registry + composeur générique contre tout littéral produit.

## 12. Exemples

`examples/adapters/` (README + `claude-code/gate-keeper.md` +
`opencode/gate-keeper.md`) : sorties réelles des adapters sur une même
définition de démonstration, marquées non normatives. Régénération :
construire la `ResolvedAgentDefinition` de démonstration puis
`get_adapter("claude-code"|"opencode").translate(...)` — jamais d'édition
manuelle.
