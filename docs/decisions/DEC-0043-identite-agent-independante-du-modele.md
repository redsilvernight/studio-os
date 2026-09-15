---
id: DEC-0043
title: 'Model-Agnostic Agent Identity : separation auth_role / agent_profile / harness / provider / model'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0043 — Model-Agnostic Agent Identity

Verrouillage architectural issu des audits Phase 0 (Model-Agnostic Agents) et
Phase 0B (Specialized Agents). Ces audits ont etabli que le coeur serveur
(`services/api/.../services/authz.py`, `services/events.py`,
`services/ai_work.py`) n'utilise jamais un nom de modele, provider ou harness
pour decider d'une autorisation — `agent_kind` n'est lu par aucune regle
metier — et que le couplage restant est documentaire (`AI/02_AGENT_RULES.md`,
`HUMAN/*`, bootstrap) et configurationnel (`.codex/agents/*.toml`).
Cette decision fige le vocabulaire et les invariants avant toute migration.

### Decision

L'identite d'un agent se decompose en cinq dimensions independantes :

1. **`auth_role`** — autorisation serveur existante, inchangee :
   `admin|developer|agent|readonly` (`TECH/04_AUTH_SYNC_CONTRACT.md`,
   DEC-0012, DEC-0036). Seule source d'enforcement des permissions serveur,
   via `Principal{machine, user, role}` et `authz.py`. **Aucun RBAC
   parallele n'est cree.**
2. **`agent_profile`** — identite fonctionnelle : ce que l'agent est cense
   faire. Valeurs actuelles : `orchestrator`, `local_worker`,
   `studio-architect`, `studio-tester`, `contract-guardian`, `sync-debugger`
   (les quatre derniers formalises par DEC-0044). Un profil ne determine PAS
   le provider, le modele, le harness, ni les permissions serveur.
3. **`harness`** — environnement d'execution (`claude-code`, `codex`,
   `opencode`, futur harness). Liste ouverte, jamais un enum ferme.
4. **`provider`** — fournisseur du modele (`anthropic`, `openai`,
   `deepseek`, `kimi`, `local`, autre). Liste ouverte, jamais un enum ferme
   sans necessite demontree.
5. **`model`** — identifiant du modele reellement utilise. Propriete
   d'execution pure : il ne determine jamais les regles metier ni les
   permissions Studi'OS.

Relation conceptuelle :

```
auth_role      → permissions serveur (seul enforcement)
agent_profile  → comportement metier (mission, interdictions, outputs)
execution profile {harness, provider, model, parametres} → comment il tourne
```

`agent_profile = studio-architect` execute sous `harness A + provider A +
model A` puis `harness B + provider B + model B` garde la meme definition
metier ; seuls profil d'execution et adaptateur changent.

### Invariants normatifs

> Changing the harness, provider, or model of an agent profile MUST NOT
> change its Studi'OS business responsibilities, prohibitions, or server
> authorization semantics.

Corollaire :

> A model identifier MUST NEVER be used as an authorization decision input.

### Statut de `agent_kind`

`agent_kind` (contrat `packages/studio-contracts/src/studio_contracts/auth.py`,
modele `services/api/.../db/models/agent.py`, migration `0001_initial.py`)
reste inchange pendant cette phase : champ historique libre, non utilise pour
l'autorisation, qui ne doit pas devenir une seconde source de verite
concurrente des nouveaux champs structures. Les valeurs historiques
(`claude-code`, `qwen-local`) restent valides et interpretables ; aucune
migration, aucun renommage, aucune reecriture d'historique. La coexistence
puis la migration vers `agent_profile/harness/provider/model` seront traitees
par la Phase 5 (sous-phase MA-6) via le workflow `contract-change`, de maniere
strictement additive.

### Consequences

- Toute future reference documentaire a un modele comme determinant de droits
  (`AI/02_AGENT_RULES.md`, `HUMAN/*`, bootstrap) est un bug de documentation
  a corriger en Phase 4 (sous-phase MA-4), pas une regle a suivre.
- DEC-0042 ("lecture seule pour Qwen par defaut") reste comportementalement
  valide mais devra etre reexprime en termes de profils en Phase 4, sans
  changer le comportement (adapteur local deja read-only pour tous,
  `packages/studio-client/src/studio_client/knowledge/memory.py`).
- Les pins `model = 'gpt-...'` de `.codex/agents/*.toml` sont reclassees
  profil d'execution (categorie B), legitimes mais a externaliser en Phase 3
  (sous-phase MA-3). Aucune regle metier n'en depend.
- Aucun changement de code, contrat, schema ou adapter dans cette phase :
  verrouillage de vocabulaire uniquement.

### Compatibilite avec les DEC existantes

DEC-0003/0011/0012 (identite machine, provisioning), DEC-0023 (auth MCP par
requete), DEC-0035 (identite des events liee a la machine), DEC-0036
(autorisation transverse role + propriete) : compatibles, non modifiees —
`auth_role` reste l'unique autorite qu'elles decrivent. DEC-0041 (revue
admin-only) : compatible — la resolution de revue reste un controle
`auth_role`, jamais un controle de profil ou de modele.
