---
id: DEC-0066
title: 'AI Library semantic content P3 : schemas par kind, ModelProfile exigences
  pures, matcher fige'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0066 — AI Library semantic content P3 : schemas par kind, ModelProfile exigences pures, matcher fige

Tranche le contrat semantique du `content` des definitions Library (gate P3,
option A acceptee). Aucune migration, aucune table, aucun endpoint, aucun
outil MCP, aucun RuntimeBinding anticipe.

## 1. Domaine canonique vs runtime : cinq proprietaires

Une information a exactement un proprietaire :

1. `canonical definition` (P1/P2, fige) : `id, kind, stable_key, scope,
   status, active_version`, liens UUID exacts. Jamais de semantique metier.
2. `semantic content` (P3, la presente) : schema par kind, valide a
   l'ecriture. Texte rule/skill, `requirements` du ModelProfile.
3. `capability requirements` (P3) : portes par `ModelProfile.content`,
   references (jamais copies) par `AgentDefinition` via
   `library_resource_links`.
4. `runtime binding` (P4, repousse) : references non secretes vers un
   runtime concret.
5. `provider-specific configuration` (adaptateurs locaux P10, hors VPS) :
   formats harness, secrets, pins `model = ...` d'outillage.

Anti-doublon : `model = ...` n'existe qu'en deux endroits legitimes et
distincts — `Agent.model` (provenance declarative d'execution, UC-5/DEC-0053)
et configuration d'adaptateur local (P10) — et jamais dans
`ModelProfile.content` ni `AgentDefinition.content`. Toute mention de
provider/modele/harness concret dans le canonique reste un bug de
documentation categorie C (DEC-0052).

## 2. ModelProfile : exigences pures, rien d'autre

`ModelProfile.content` = `{content_schema, requirements:
CapabilityRequirement, description?}`. Interdits (rejetes par
`extra="forbid"`) : provider concret, modele concret, harness, endpoint,
cle/secret, famille fournisseur, version d'API fournisseur, ranking,
whitelist de fournisseurs ou modeles. Le choix du runtime/modele concret
n'appartient pas a P3.

## 3. AgentDefinition : definition logique, jamais instance d'execution

`AgentDefinition.content` = `{content_schema, summary?, intended_use?}`.
Aucune capability inline, aucun provider/modele/harness/runtime concret
(`extra="forbid"`). Les requirements s'obtiennent exclusivement via un lien
`AgentDefinition -> ModelProfile`. Un AgentDefinition sans ModelProfile est
valide et signifie qu'aucune exigence particuliere n'est exprimee. Le
modele historique de DEC-0044 n'est pas ressuscite : son corps reste une
trace figee d'une decision supersedee, sans valeur normative.

## 4. Rule/Skill/Workflow

`rule` et `skill` : `{content_schema, text}` avec `1 <= len(text) <= 65_536`
caracteres. Budget propre a Library, sans rapport avec le budget dur
256 Kio du Context Package (DEC-0057), qui borne un paquet compose, jamais
une version stockee. `workflow` : contenu libre, explicitement repousse a
P11.

## 5. Validation et `content_schema`

- Envelope commun minimal + schemas par kind (union discriminee par
  `kind`), `extra="forbid"` conforme a la convention `ContractModel`.
- Marqueur `content_schema: "studio.library.<kind>/v1"` **dans** le document
  stocke : version d'artefact Library (analogue au `schema_version` du
  manifeste DEC-0057, dont la tension avec DEC-0048 est levee), jamais une
  version generique des payloads MCP/API (DEC-0048/CC-3 inchanges).
- Validation applicative a l'ecriture, au point unique
  `_create_version_row` (creation initiale et nouvelle version), toujours
  apres les gates scope/ownership : un 422 ne decrit que le payload de
  l'appelant — la validation n'est jamais un oracle sur des ressources
  invisibles (`403`/`404` avant `422`). Aucune DDL.
- Erreur : `422 {"error_code": "invalid_content", "details":
  [{field, reason}]}`.

## 6. Durcissement contractuel P3

Le passage de `content` libre a `content` valide est un durcissement
contractuel de P3 (meme categorie que DEC-0025/DEC-0036), documente ici et
en `TECH/02`/`TECH/05`. Concretement : avant P3, `content:
dict[str, object] = {}` acceptait tout dictionnaire, y compris `{}` ;
depuis P3, `rule`/`skill`/`model_profile`/`agent_definition` exigent un
`content_schema` valide et un contenu conforme, sinon `422
invalid_content` — un payload qui passait en 201 peut desormais etre
rejete. L'ancien `dict[str, object]` n'a jamais constitue un contrat
semantique stable et n'est pas invoque comme tel.

Pas de bump de version, par exemption documentee (precedent DEC-0025) :
aucun consommateur conforme n'existe a ce stade — verifie par lecture
directe : `packages/studio-client` ne contient aucun code Library,
`services/mcp` n'expose aucun outil Library, `dashboard/src` ne consomme
aucune route Library (seul l'artefact OpenAPI regenere y fait reference).
Les payloads de tests P1/P2 sont mis a jour vers le contrat durci sans
changer leur semantique (statuts, versioning, resolution). Caveat repris
de DEC-0025 : le premier consommateur reel (HTTP tiers, outil MCP,
adaptateur) devra traiter le contenu valide comme requis des la
conception ; toute evolution incompatible ulterieure suivra alors
`contract-change` avec bump explicite.

## 7. Matcher fige (open strings, aucun ranking)

`coding`, `context_window_min` (runtime >= requirement), `tools_required`
(subset), `local_compatible` : correspondances actuelles conservees.
`reasoning`, `multimodal`, `cost`, `latency` : egalite stricte de tags —
aucun ranking implicite (`low < medium < high` interdit). Invariant absolu :
`unknown != compatible` (dimension requise non decrite = non-match) ;
`CapabilityRequirement()` vide reste compatible avec tout. L'ajout futur
d'une dimension a `CapabilityRequirement` exige dans le meme changement
l'extension de `check_compatibility` et ses tests : sans cela, le
fail-closed ne serait pas garanti (le matcher est une liste explicite,
pas un registre).

## 8. Evolution

Ajout de champ optionnel : additif. Changement incompatible de forme :
nouveau `content_schema` en coexistence (meme philosophie que DEC-0048
regle 5). Aucune mutation retroactive d'une version immuable. Les exemples
et fixtures restent neutres (`provider_a`, `model_a`, ...) : aucun
Claude/OpenAI/Ollama/Kimi n'est normatif dans le domaine canonique.

## 9. Securite

Invariants P1/P2 intacts : filter-first, isolation User en 404, UUID
canonique, pins exactes, liens vers versions exactes, locks advisory,
erreurs non revelatrices, resolution deterministe (resolver P2 inchange).
`check_compatibility` ne s'evalue que sur la definition effective deja
resolue (post-filtre P2), jamais sur des candidats invisibles.

## 10. Compatibilite avec les DEC existantes

Additif au sens des regles contracts (+ `contract-guardian`,
`studio-tester`) : nouveaux schemas, 422 documente en OpenAPI, docs
`TECH/02`/`TECH/05` dans le meme lot. Ne modifie ni ne rouvre
DEC-0043/0044/0048/0052/0053/0057/0062-0065. Repousse explicitement :
bindings (P4), resolver complet (P5), Runtime Registry (P6), HTTP (P7),
MCP (P8), Context Package (P9), adaptateurs (P10), workflows (P11),
UI/Inspector (P12), E2E (P13).
