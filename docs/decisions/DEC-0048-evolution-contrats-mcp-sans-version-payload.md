---
id: DEC-0048
title: 'CC-3 : evolution des contrats MCP par discovery + schemas, sans version par
  payload'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:29dee6ea0a05fe39027d21eafe43e16a0a41e57b1da2b32491e8ae450c04a5d8
---

# DEC-0048 — CC-3 : evolution des contrats MCP par discovery + schemas, sans version par payload

L'audit CC-3 (28 outils : 25 VPS + 3 locaux UC-3, SDK `mcp==2.2.0`) a
etabli que le vrai manque n'est pas l'absence d'un numero de version dans
chaque reponse, mais l'absence d'output schemas machine-discoverables :
`tools/list` expose un `inputSchema` reel par outil et un `outputSchema`
factice (`additionalProperties: True`, auto-genere depuis `dict[str, Any]`).
Un champ `version` ou `schema_version` par payload ne resoudrait aucun
scenario de rupture reel (il ne decrit aucune forme) et entrerait en
collision avec deux homonymes existants : `Task.version` (revision de
ressource, concurrence optimiste) et `EventEnvelope.schema_version`
(version de schema event). Cette decision fige la regle d'evolution.

### Decision

1. Aucun champ `version` / `schema_version` n'est ajoute aux reponses MCP
   (succes comme erreurs `{error_code, message, ...}` in-band). L'absence
   de `version` sur `studio_memory_search`, `studio_memory_read` et
   `studio_graph_query` (UC-3/DEC-0047) est explicitement conforme, pas une
   dette.
2. MCP protocol version (negociee a `initialize`, ex. `2026-07-28`) n'est
   pas le contrat d'outil Studi'OS. Le contrat d'un outil = son nom + son
   `inputSchema` + son `outputSchema` + sa description exposes via
   `tools/list`. Ne jamais les confondre.
3. Les changements additifs restent compatibles sans bump ni nouvelle
   surface : nouveau tool, input optionnel, champ output optionnel,
   nouveau `error_code` des lors que le fallback code-inconnu-erreur
   generique est respecte. Un consommateur conforme ignore l'inconnu.
4. Les breaking changes ne sont jamais silencieux : suppression/renommage,
   nouvel input required, changement incompatible de type, enum retreci,
   suppression/renommage d'un `error_code`. Ils suivent `contract-change`
   (Decision + doc + mocks/fixures a jour) comme tout contrat versionne.
5. Lorsqu'un ancien contrat doit continuer a fonctionner, creer une
   nouvelle surface nommee explicitement (par exemple suffixe `_v2`) avec
   coexistence bornee : les deux noms coexistent dans `tools/list`, chaque
   consommateur choisit. Aucune duree generique de coexistence `_v1/_v2`
   n'est fixee ici : elle sera decidee lorsqu'une vraie rupture apparaitra.
6. Les output schemas explicites sont le mecanisme cible de discovery des
   formes de sortie. Dette enregistree (`TECH/07`) : les 28 `outputSchema`
   actuels ne decrivent pas leurs outputs ; des schemas explicites sont
   requis avant toute evolution breaking sure d'un tool reellement
   consomme. Ils ne sont pas implementes par cette decision.
7. `_meta` (metadata d'outil du protocole MCP, inutilisee a ce jour) reste
   reservee comme vehicule futur possible d'une metadata de contrat, jamais
   dans le payload. Non utilisee maintenant (YAGNI : aucun consommateur
   externe).
8. Les `error_code` restent du ressort de CC-4 (taxonomie, stabilite,
   catalogue). CC-3 ne tranche que leur independance au versionnement de
   schema et la compatibilite de l'enveloppe in-band avec de futurs
   schemas union succes/erreur.

### Consequences

- Aucune modification runtime, aucune migration, aucun rename : clarification
  contractuelle uniquement (amendement `TECH/07`, clarification UCC §12).
- Tant qu'aucun consommateur reel n'est recense sur un tool, une evolution
  directe documentee reste possible (application de `TECH/07` : rupture
  seulement face a un consommateur reel) — la regle 5 s'applique des qu'une
  coexistence est necessaire.
- Ne pas copier `/api/v1` en MCP : aucune version de transport Studi'OS
  prefixee sur les noms d'outils.

### Compatibilite avec les DEC existantes

Precise `TECH/07` (charges non versionnees) sans le contredire : l'additif
est desormais explicitement autorise, le breaking exige une surface en cas
de coexistence. Compatible DEC-0046 (discovery par transport, `tools/list`
= verite), DEC-0047 (UC-3 conforme sans version), DEC-0023 (constat
d'origine rappele en `TECH/07`), skill `contract-change` (regles
additive/breaking etendues aux contrats d'outils MCP).
