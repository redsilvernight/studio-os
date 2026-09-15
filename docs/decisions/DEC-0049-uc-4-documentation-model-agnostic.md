---
id: DEC-0049
title: 'UC-4 : documentation model-agnostic du consommateur (roles fonctionnels, zero couplage modele)'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0049 — UC-4 : documentation model-agnostic

Rectifie le couplage documentaire identifie par l'audit du consommateur
universel du 2026-09-15 (categorie C restante) : `AI/02_AGENT_RULES.md`,
`AI/03_CONTEXT_BOOTSTRAP.md` et `HUMAN/*` presentaient des noms de modele
(Claude/Qwen) comme des roles produit, contredisant DEC-0043 amendee et
`docs/PRODUCT_VS_DEV_TOOLING.md`. Aucun code, contrat, schema ou endpoint
touche : documentation uniquement.

### Decision

1. Les sections de `AI/02_AGENT_RULES.md` nommees d'apres un modele
   deviennent des roles fonctionnels : « Orchestrateur » et « Agent
   d'execution locale ». Un preambule rappelle que harness/provider/modele
   sont des choix d'execution, jamais des roles, et qu'un consommateur sans
   profil suit les memes regles.
2. Les regles comportementales exprimees comme « Qwen est read-only »
   sont reexprimees sans nom de modele : « la memoire partagee est en lecture
   seule par defaut » (`AI/01`, `AI/03`, `HUMAN/02`, `HUMAN/05`, `00_README`,
   `IMPLEMENTATION/04`). Le comportement est inchange.
3. `HUMAN/01`, `HUMAN/02`, `HUMAN/03`, `00_README`, `README.md` : les
   mentions de modele utilisees comme roles ou comme prerequis sont remplacees
   par des termes generiques (« agent IA », « agent d'execution »,
   « orchestrateur »).
4. `TECH/09` : la sous-section « Qwen » devient « Agents » et reexprime la
   lecture seule par defaut pour tout agent non privilegie.
5. `TECH/05` : l'exemple d'`agent_kind` ne cite plus de noms de modele.
6. DEC-0042 recoit un amendement UC-4 : l'invariant « lecture seule sur la
   memoire partagee par defaut » est reexprime sans nom de modele ; les
   mentions historiques du corps sont conservees comme contexte d'epoque
   (categorie D), pas comme regle.
7. Les references historiques legitimes (corps des DEC-0042 et des
   breakdowns, pins de modele de `.codex/agents/*.toml`) sont conservees
   (categories A/D) ; les fixtures de test `agent_kind="claude_code"` restent
   des donnees, pas de la logique (categorie B).

### Consequences

- Les documents publics lus par un consommateur externe ne presentent plus
  aucun modele comme role, prerequis ou determinant de droits.
- Aucun changement de comportement : la lecture seule par defaut etait et
  reste un invariant d'implementation (`packages/studio-client/.../knowledge/`).
- `docs/PRODUCT_VS_DEV_TOOLING.md` reste la reference de la frontiere
  produit/outillage.

### Compatibilite

Precise DEC-0043 amendee sans la contredire ; complete UC-1/UC-2/UC-3 ; ne
touche a aucun contrat versionne (`TECH/02/03/04`), aucun schema, aucun code
runtime. Les contrats `TECH/05` et `TECH/09` ne sont modifies qu'en
documentation, sans changement de forme ni d'enum.
