---
id: DEC-0044
title: 'Specialized Agent Profiles : studio-architect, studio-tester, contract-guardian,
  sync-debugger comme agent_profiles harness-agnostic'
status: superseded
date: '2026-09-15'
superseded_by: DEC-0043
source: docs/DECISIONS.md
sync_hash: sha256:e99e541c69acdc57e3c91ccdd10c3d393aef39b157a4f9317f8891ea9134eb14
---

# DEC-0044 — Specialized Agent Profiles : studio-architect, studio-tester, contract-guardian, sync-debugger comme agent_profiles harness-agnostic

> **Rectification Phase 1 (2026-09-15).** Cette decision est supersedee par
> l'amendement de DEC-0043. Hypothese corrigee : `studio-architect`,
> `studio-tester`, `contract-guardian` et `sync-debugger` sont des **outils
> internes de developpement du repository** (voir
> `docs/PRODUCT_VS_DEV_TOOLING.md`), pas des `agent_profiles` du runtime
> produit. Les eriger en profils produit institutionnalisait a tort le
> tooling de developpement dans l'architecture publique, et laissait entendre
> qu'un `agent_profile` predefini est requis pour consommer Studi'OS — ce qui
> est faux (un consommateur externe sans profil obtient l'interface complete
> que son `auth_role` autorise). Le corps historique est conserve ci-dessous
> sans modification, a titre de trace.

---

# DEC-0044 — Specialized Agent Profiles (corps historique, fige)

Compagne de DEC-0043 (qui fige `auth_role / agent_profile / harness /
provider / model`). L'audit Phase 0B a etabli que les quatre agents
specialises existent aujourd'hui sous une seule representation,
`.codex/agents/*.toml`, melangeant definition metier et profil d'execution
dans un format Codex-only, sans declaration d'outils ni de permissions. Cette
decision les erige en `agent_profiles` Studi'OS et fige le principe de leur
migration, sans migrer quoi que ce soit dans cette phase.

### Decision

1. `studio-architect`, `studio-tester`, `contract-guardian` et
   `sync-debugger` sont des **agent_profiles Studi'OS** (au sens de
   DEC-0043), pas des agents Codex, Claude ou OpenCode. Leur comportement
   metier est preserve a l'identique :
    - `studio-architect` : analyse d'architecture, read-only, sorties
      Systems/Contracts/Dependencies/Risks/Recommendation/Files, Graphify
      `path/explain` aux frontieres Bloc A/B ;
    - `contract-guardian` : revue de conformite des contrats, report-only,
      verdict Additive/Breaking/Needs a Decision/Compliant, regles
      Idempotency-Key et enveloppe Event ;
    - `studio-tester` : validation proportionnee Tier 1-3, seul profil a
      execution (pytest/ruff/mypy, chemins offline/transfert reels en Tier 3),
      interdiction de fixer ou d'inventer un test ;
    - `sync-debugger` : diagnostic de cause racine sync/offline/claims/
      transfert, read-only, separation explicite etat client (SQLite) vs
      serveur (Postgres).
    La strategie de contexte commune (plus petit paquet autonome, diff cible,
    sorties concises, "Not tested" explicite) fait partie de ces invariants.
2. Principe adopte — source canonique puis adaptateurs :
    ```
    Canonical Agent Definition (.agents/definitions/, futur)
            │
            ▼
      Harness Adapter (adapters/codex|opencode|claude/, conceptuels)
            │
            ▼
      Execution Profile (harness, provider, model, parametres)
            │
            ▼
      Provider / Model
    ```
    Les fichiers `.codex/agents/*.toml` restent temporairement les
    implementations existantes et ne sont pas modifies dans cette phase. Les
    definitions `.agents/definitions/*` seront creees en Phase 2 (sous-phase
    MA-2) par extraction a comportement constant, sans reecriture
    fonctionnelle.
3. Contenu normatif de la future definition canonique (invariants metier
   portables uniquement) : mission, responsabilites, interdictions,
   strategie de contexte, criteres de validation, outputs attendus, regles
   Graphify, regles memoire, regles Git, regles contrats, besoins
   conceptuels en outils. Elle ne contiendra jamais : modele, provider,
   syntaxe propre au harness, format d'invocation proprietaire,
   configuration technique Codex/OpenCode/Claude.
4. Responsabilite des adaptateurs : traduire la definition canonique vers le
   harness (format de configuration, declaration permissions/outils,
   mecanisme de subagent, syntaxe d'invocation, modele/provider, reasoning
   effort, limites propres au harness). Un adaptateur ne redéfinit jamais
   les regles metier. Les pins actuels (`gpt-6-astra` pour architect,
   `gpt-5.6-terra` pour les trois autres, `model_reasoning_effort`) sont
   reclassees profil d'execution : configuration legitime a externaliser,
   pas definition metier.
5. Trois notions de capability, sans RBAC parallele :
    - **Agent tool requirements** (conceptuels, ex. `repository.read`,
      `repository.search`, `tests.run`) : besoins du profil, traduits par
      chaque adaptateur en permissions harness. Ni permissions serveur, ni
      enforcement ;
    - **Server permissions** : `auth_role` + ownership via `authz.py`
      (DEC-0036), seul enforcement. Rien d'autre ;
    - **Harness capabilities** (ex. read, grep, bash, edit, delegation de
      tache) : ce que l'environnement permet techniquement.
6. Rappel normatif (DEC-0043, s'applique a chaque profil) : changer le
   harness, le provider ou le modele d'un profil NE DOIT PAS changer ses
   responsabilites metier, ses interdictions, ni sa semantique
   d'autorisation serveur ; un identifiant de modele NE DOIT JAMAIS servir
   d'entree a une decision d'autorisation.

### Consequences

- Aucun fichier cree sous `.agents/definitions/`, `.opencode/agents/` ou
  `adapters/` dans cette phase ; aucune modification des TOML, des contrats,
  des modeles DB, d'`authz.py`, ni des comportements des quatre agents.
- `brainstormer` et `godot-tester`, sans definition dans ce depot, restent
  des dependances globales externes, hors perimetre de cette decision.
- Les mentions historiques des agents dans les DEC et breakdowns
  (`contract-guardian` releve, `studio-tester` valide, ...) restent valides
  comme tracabilite d'usage ; elles designeront desormais des profils, pas
  des implementations Codex.
- Phase 2 (sous-phase MA-2) : extraction des definitions canoniques, avec
  mecanisme anti-drift entre canonique et TOML sur le modele de
  `scripts/adr_index.py --check`.

### Compatibilite avec les DEC existantes

Compatible avec DEC-0043 (dont elle est l'application aux quatre profils),
DEC-0023/0035/0036 (auth et autorisation inchangees), et l'ensemble des DEC
de roadmap : aucune ne pinne un modele dans une regle metier.
