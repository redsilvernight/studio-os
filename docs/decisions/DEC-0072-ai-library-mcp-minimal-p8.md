---
id: DEC-0072
title: 'AI Library MCP minimal P8 : 5 outils use-cases sur services communs, output schemas explicites'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0072 — AI Library MCP minimal P8 : 5 outils use-cases sur services communs, output schemas explicites

Ferme le gate P8 (« Surface MCP petite et stable ») : les capacites
P1–P6, canoniques en HTTP depuis P7 (DEC-0071, 20 operations), sont
desormais consommables par un agent/harness compatible MCP via 5 outils
orientés use-cases — pas via une transposition mecanique des 20
operations REST. P8 n'ajoute aucune logique metier : chaque handler est
mince (`outil MCP → meme service → memes contrats domaine`, jamais
`MCP → HTTP localhost`, DEC-0005 inchangee).

## 1. Surface retenue (20 operations HTTP → 5 outils)

| Tool | Use case | Service | Mutation | Idempotence |
|---|---|---|---|---|
| `studio_resolve_agent` | definition logique complete a utiliser (+ override session ephemere) | `resolution.resolve_full` (kind fixe `AGENT_DEFINITION`) | non | N-A (lecture pure) |
| `studio_discover_definitions` | discover/read sans UUID (filtres, ou `resource_id`, ou kind+`stable_key`, `include_versions?`) | `library.list/get/versions` (+ `resolve_definition` P2 pour la cle logique) | non | N-A |
| `studio_publish_definition` | publier : `create`/`create_version`/`activate`/`deprecate` | 4 fn `library.*` (creation et activation separees, DEC-0064) | oui | `idempotency_key` |
| `studio_configure_runtime` | `set`/`clear` le runtime d'une cle `(kind, stable_key)` | `bindings.create` / `list`+`delete` | oui | `set` supporte, `clear` N-A |
| `studio_register_runtime` | `register`/`update`/`revoke` son runtime (refs ouvertes) | 3 fn `registry.*` | oui | `register`/`update` supportes, `revoke` N-A |

## 2. Pourquoi cette surface est minimale

Fusionnes : discover+read (un selecteur, pas `get_by_id`/`get_by_key`/
`list_by_kind`) ; publish lifecycle (un verbe `action`, les 4
semantiques restant des appels de services distincts) ; set/clear
runtime ; register/update/revoke. Non transposes : les 10 routes
Library et les 9 P4/P6 ne deviennent pas 19 outils. Volontairement
absents : `resolve_definition` P2 seul (redondant avec P5 canonique,
DEC-0071 §2), locks projet (lus via la resolution, coordination
humaine), lecture Registry detaillee, P9 (Context Package), P10
(adaptateurs, execution LLM), discovery vendor, catalogue model,
auto-selection. Test d'equilibre §29 : aucun des 5 ne peut etre
supprime sans perdre un use-case ; aucun ne melange des intentions
sans coherence metier.

## 3. HTTP = reference semantique, granularite adaptee

Memes identites, scopes, ownership, bindings, resolution P5, erreurs
metier, compatibilite, versioning qu'en HTTP. Seule la granularite
change (use-case vs REST). Parite prouvee par tests (router HTTP direct
vs outil MCP, meme session/meme Principal).

## 4. Principal avant idempotence

`run_tool` resout `Principal` avant le handler ; chaque mutation fait
`ensure_can_write` avant le court-circuit `run_idempotent_dict`
(comme HTTP et les 5 outils idempotents historiques). Espace de cles
distinct de HTTP (`MCP <outil>`, DEC-0027). Teste : `readonly` +
cle fraiche → `forbidden` sans reservation, puis writer + meme cle →
succes.

## 5. Output schemas explicites (dette DEC-0048 §6 partiellement resorbee)

Annotation de retour `ModeleSucces | McpError` (`McpError` =
`{error_code, message}` + extras preservés, meme vocabulaire que les
services, pas de seconde taxonomie) ; `structured_output` auto-detecte
du SDK en derive l'`outputSchema`. Les 29 outils historiques restent en
`dict[str, Any]` (additif : intouches). Aucun `version`/
`schema_version` en payload (DEC-0048).

## 6. Resolution

`ResolvedAgentDefinition` complet (definition, version, rules, skills,
profil, requirements, runtime, compatibilite, provenance, scopes,
binding level/override) — jamais reduit a prompt/modele.
`runtime_incompatible` structure sans fallback. Override session :
valide comme un choix stocke (404/403), gagnant selon P4, trace
(`session_override`), jamais persiste (`DB unchanged` teste).

## 7. Politique additive/breaking (DEC-0048)

Ajout pur : 5 nouveaux tools, aucun existant modifie ni renomme,
aucun bump. Rupture future : `contract-change` + surface `_v2`
coexistante si consommateur reel. Pas de `version` transport sur les
noms d'outils.

## 8. Erreurs

Enveloppe in-band `{error_code, message, ...}` inchangee ;
`definition_not_found`, `invalid_runtime_binding` (avec `reason`, ex.
`ephemeral_level_not_stored`), `runtime_incompatible`, `already_bound`,
`runtime_not_found`, `version_conflict`, `forbidden`,
`unauthenticated`, `invalid_argument`, `not_found`,
`idempotency_key_payload_mismatch` documentes en description d'outil.

## 9. Frontieres P9/P10

Aucun tool `give_me_everything`, aucune execution de modele, aucun
appel LLM/provider, aucun choix automatique de runtime, aucune branche
provider-specific (`ollama` = runtime normal, teste).
