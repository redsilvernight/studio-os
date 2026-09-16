---
id: DEC-0043
title: 'Model-Agnostic Agent Identity : separation auth_role / harness / provider
  / model, agent_profile optionnel'
status: active
date: '2026-09-15'
supersedes: DEC-0044
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:97c7ecc6ff0d3289d2d7e95c38f26efab2176c33eeafe6f15ec3eeeef5b16f05
---

# DEC-0043 — Model-Agnostic Agent Identity : separation auth_role / harness / provider / model, agent_profile optionnel

## Amendement — rectification Phase 1 (2026-09-15)

La version initiale de cette decision listait `orchestrator`,
`local_worker`, `studio-architect`, `studio-tester`, `contract-guardian` et
`sync-debugger` comme valeurs d'`agent_profile`, et DEC-0044 erigeait les
quatre derniers en `agent_profiles` produit. Cette formulation etait
incorrecte : les quatre agents specialises sont des **outils internes de
developpement du repository Studi'OS** (harness de dev, portage OpenCode
separe eventuel), pas des roles fonctionnels du runtime produit. Exiger ou
suggerer un `agent_profile` predefini pour consommer Studi'OS contredit
l'objectif produit : **un agent externe totalement inconnu, sans
`agent_profile`, doit pouvoir utiliser Studi'OS**.

Le present amendement corrige ce point sans creer de decision
contradictoire ; l'historique est preserve ci-dessous. DEC-0044 est
supersedee par le present amendement. Sont conserves : la separation
`auth_role` / `harness` / `provider` / `model`, les invariants normatifs, le
statut d'`agent_kind`, et `auth_role` comme seule autorite serveur.

## Contexte d'audit (inchange)

Verrouillage architectural issu des audits Phase 0 (Model-Agnostic Agents) et
Phase 0B (Specialized Agents). Ces audits ont etabli que le coeur serveur
(`services/api/.../services/authz.py`, `services/events.py`,
`services/ai_work.py`) n'utilise jamais un nom de modele, provider ou harness
pour decider d'une autorisation — `agent_kind` n'est lu par aucune regle
metier — et que le couplage restant est documentaire (`AI/02_AGENT_RULES.md`,
`HUMAN/*`, bootstrap) et configurationnel (`.codex/agents/*.toml`, outillage
de developpement uniquement).
Cette decision fige le vocabulaire et les invariants avant toute migration.

### Decision (amendee)

L'identite d'un agent se decompose ainsi :

1. **`auth_role`** — autorisation serveur existante, inchangee :
   `admin|developer|agent|readonly` (`TECH/04_AUTH_SYNC_CONTRACT.md`,
   DEC-0012, DEC-0036). Seule source d'enforcement des permissions serveur,
   via `Principal{machine, user, role}` et `authz.py`. **Aucun RBAC
   parallele n'est cree.**
2. **`agent_profile`** — **metadonnee optionnelle** : classification
   fonctionnelle declarative (ce que l'agent dit faire), information
   d'observabilite et d'audit (AIWorkLog, statistiques, reproduction de
   session). Un profil ne determine PAS le provider, le modele, le harness,
   ni les permissions serveur. **Un consommateur externe sans
   `agent_profile` utilise Studi'OS exactement comme un consommateur avec
   profil, a `auth_role` egal.** `agent_profile` n'est jamais une whitelist
   des agents autorises, jamais une entree d'autorisation, jamais un
   discriminant de capacites serveur.
3. **`harness`** — environnement d'execution (`claude-code`, `codex`,
   `opencode`, futur harness inconnu). Chaine ouverte, jamais un enum ferme.
4. **`provider`** — fournisseur du modele (`anthropic`, `openai`,
   `deepseek`, `kimi`, `local`, autre, futur provider inconnu). Chaine
   ouverte, jamais un enum ferme sans necessite demontree.
5. **`model`** — identifiant du modele reellement utilise (futur modele
   inconnu inclus). Propriete d'execution pure : il ne determine jamais les
   regles metier ni les permissions Studi'OS.

Relation conceptuelle :

```
auth_role      → permissions serveur (seul enforcement)
agent_profile  → metadonnee fonctionnelle optionnelle (observabilite, audit)
execution profile {harness, provider, model, parametres} → comment il tourne
```

`orchestrator` et `local_worker` restent des etiquettes documentaires
historiques (repartition du travail humain/IA dans `AI/02_AGENT_RULES.md`),
pas des concepts serveur : rien dans le coeur ne les lit, ne les exige, ni
ne s'y adapte. `studio-architect`, `studio-tester`, `contract-guardian` et
`sync-debugger` ne sont PAS des `agent_profiles` produit : voir
`docs/PRODUCT_VS_DEV_TOOLING.md` et DEC-0044 (supersedee).

### Invariants normatifs (inchanges)

> Changing the harness, provider, or model of an agent MUST NOT
> change its Studi'OS business responsibilities, prohibitions, or server
> authorization semantics.

Corollaires :

> A model identifier MUST NEVER be used as an authorization decision input.

> The absence of an `agent_profile` MUST NEVER deny, restrict, or alter
> server authorization or capabilities : unknown external consumers get the
> full interface their `auth_role` allows.

> No `if model == ... / if provider == ... / if harness == ...` branch in
> central business logic, sauf integration explicitement specifique et isolee.

### Statut de `agent_kind` (inchange)

`agent_kind` (contrat `packages/studio-contracts/src/studio_contracts/auth.py`,
modele `services/api/.../db/models/agent.py`, migration `0001_initial.py`)
reste inchange pendant cette phase : champ historique libre, non utilise pour
l'autorisation, qui ne doit pas devenir une seconde source de verite
concurrente des nouveaux champs structures. Les valeurs historiques
(`claude-code`, `qwen-local`) restent valides et interpretables ; aucune
migration, aucun renommage, aucune reecriture d'historique. Les futurs champs
structures `harness/provider/model` (chaines ouvertes, observabilite
uniquement) seront traites par le nouveau roadmap (sous-phase UC-5) via le
workflow `contract-change`, de maniere strictement additive.

### Consequences (amendees)

- Toute future reference documentaire a un modele comme determinant de droits
  (`AI/02_AGENT_RULES.md`, `HUMAN/*`, bootstrap) est un bug de documentation
  a corriger (sous-phase UC-4 du roadmap recalcule), pas une regle a suivre.
- DEC-0042 ("lecture seule pour Qwen par defaut") reste comportementalement
  valide mais devra etre reexprime sans nom de modele (adaptateur local deja
  read-only pour tous,
  `packages/studio-client/src/studio_client/knowledge/memory.py`).
- Les pins `model = '...'` de `.codex/agents/*.toml` sont reclassees profil
  d'execution d'outillage de developpement (categorie A : integration
  specifique legitime, hors produit). Aucune regle metier n'en depend.
- Aucun changement de code, contrat, schema ou adapter dans cette phase :
  verrouillage de vocabulaire uniquement.

### Compatibilite avec les DEC existantes (inchangee)

DEC-0003/0011/0012 (identite machine, provisioning), DEC-0023 (auth MCP par
requete), DEC-0035 (identite des events liee a la machine), DEC-0036
(autorisation transverse role + propriete) : compatibles, non modifiees —
`auth_role` reste l'unique autorite qu'elles decrivent. DEC-0041 (revue
admin-only) : compatible — la resolution de revue reste un controle
`auth_role`, jamais un controle de profil ou de modele.
