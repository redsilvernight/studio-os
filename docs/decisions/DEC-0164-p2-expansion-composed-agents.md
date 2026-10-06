---
id: DEC-0164
title: 'AI Bootstrap P2 : expansion récursive de composed_agent dans le moteur P5, sans second moteur'
status: active
date: '2026-09-28'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0164 — AI Bootstrap P2 : expansion récursive de `composed_agent`

Complète **DEC-0069 §3**, qui préservait délibérément `composes_agent` sans
expansion (« sémantique non définie »). L'étape P2 de la roadmap *Project AI
Bootstrap* (tâche `03fd9946`) demande de lever cette limite pour produire un
plan de bootstrap qui décrit un agent composé jusqu'au bout, pas seulement sa
référence. Prépare le terrain pour **DEC-0144** (AIB-B, plan de bootstrap
agrégé côté serveur) : `resolve_full` peut désormais décrire un agent composé
en entier, condition nécessaire à l'agrégation multi-agents que DEC-0144
prévoit (tâche `fbda9b07`, non traitée ici).

## 1. Sémantique choisie

`composed_agent` est désormais résolu **récursivement, avec le même cœur pur**
(`resolve_agent`, `packages/studio_contracts/resolution.py`) : chaque agent
composé produit son propre `ResolvedAgentDefinition` complet et indépendant
(mêmes règles de dédup de rules/skills, localement à ce nœud — aucune fusion
ni aplatissement inter-arbres inventée). Aucune sémantique d'exécution n'est
introduite : un agent composé reste décrit, jamais exécuté, exactement comme
avant pour l'agent racine. Cela ne préjuge toujours de rien côté workflows
(`references_workflow` reste préservé sans expansion, hors périmètre P2,
sémantique d'exécution toujours P11).

## 2. Un seul moteur

Le corps de `resolve_agent` est extrait en fonction interne récursive prenant
`visited` (chemin de composition parcouru) et `depth`. `resolve_agent` reste
l'unique point d'entrée public ; la résolution d'un agent composé est un appel
interne à cette même fonction sur son propre sous-graphe (déjà présent dans le
snapshot fourni par l'appelant) — jamais un second algorithme, jamais une
copie divergente.

## 3. Garde-fous fail-closed

- Cycle direct (`A compose A`) ou transitif (`A → B → A`) le long du chemin de
  composition → nouveau code fermé `composition_cycle_detected`, jamais de
  boucle silencieuse ni de troncature muette.
- Profondeur bornée (`MAX_COMPOSITION_DEPTH = 8`, constante documentée dans le
  code) → `composition_depth_exceeded` au-delà, jamais de récursion non
  bornée côté cœur pur ni côté chargeur DB (`resolve_full`).
- Les deux codes rejoignent le vocabulaire fermé de `ResolutionErrorCode` et
  sont mappés `422` côté service (même famille que `invalid_resolution_input`
  — données déjà visibles de l'appelant, pas de nouvel oracle DEC-0065 §2).

## 4. Classification contractuelle

**Breaking**, au sens du skill `contract-change` : la *forme* d'un champ
existant change (`ResolvedAgentDefinition.composed_agents` passe de
`list[PreservedReference]` à `list[ResolvedComposedAgent]`, qui porte en plus
le sous-arbre résolu). Le nom du champ et son intention ne changent pas,
seule sa profondeur d'information augmente — mais un consommateur qui
désérialisait `composed_agents` comme une simple liste de références plates
voit sa forme changer et doit être corrigé dans le même changement.

Consommateurs identifiés et traités :

- `POST /resolutions` (DEC-0071 P7) et `studio_resolve_agent` MCP (DEC-0072
  P8) : aucun modèle miroir propre, ils sérialisent `ResolvedAgentDefinition`
  tel quel — suivent le changement sans code à modifier.
- Dashboard Resolution Inspector (DEC-0076 P12) : `dashboard/openapi.json` et
  `dashboard/src/openapi-schema.ts` régénérés dans le même changement ;
  `dashboard/src/libraryFormat.ts` n'utilise `composes_agent` que comme
  étiquette de `BindingRelation` (non affecté) et aucune vue ne consomme
  encore le contenu de `composed_agents` (fixtures à `[]` dans
  `inspector.test.ts`/`e2e/p13.spec.ts`) — pas de logique réelle à corriger,
  seulement les types régénérés.
- **`packages/studio-client` (Bloc B, adaptateurs P10, DEC-0074)** : lecteur
  réel de `composed_agents` (`adapters/base.py`, avertissement
  `composed_agents_not_expanded`) — **corrigé dans ce changement** :
  `adapters/base.py` lit désormais `reference.kind`/`reference.stable_key`
  et le code d'avertissement devient `composed_agents_resolved_not_rendered`
  (l'agent composé est résolu, mais cet adaptateur ne rend toujours que
  l'agent racine). `tests/client/adapters/test_adapters_p10.py` et
  `tests/api/test_p13_e2e.py` (P13, DEC-0077) mis à jour pour la nouvelle
  forme imbriquée.

Pas de `schema_version` dédié côté Library (pas d'enveloppe versionnée sur ce
type) ; traité comme DEC-0069 §10 — durci, documenté, sans consommateur non
identifié restant.

## 5. Hors périmètre

- `skill → rule` reste à un niveau : structurellement le seul niveau possible
  (`RULE` n'a aucune arête sortante dans `binding_relation_for`). Le
  multi-niveau vient uniquement du graphe `composed_agent` ; chaque agent
  composé résout ses propres skills→rules dans son propre sous-arbre.
- Le plan de bootstrap agrégé côté serveur (tâche `fbda9b07`, endpoint
  multi-ressources / AIB-B, DEC-0144) reste hors périmètre de cette décision
  — session de suivi, une fois ce moteur récursif disponible comme primitive.
