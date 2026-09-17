---
id: DEC-0069
title: 'AI Library Resolution Engine P5 : coeur pur, provenance, erreur stricte'
status: active
date: '2026-09-17'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0069 — AI Library Resolution Engine P5 : cœur pur, provenance, erreur stricte

Assemble les briques P1–P4 en une spécification logique résolue,
déterministe, explicable et harness-neutral (gate P5). Aucune architecture
parallèle : un seul cœur pur, une seule implémentation de la précédence,
aucun troisième resolver indépendant.

## 1. Séparation acquisition / résolution pure

- Chargement (service `studio_api/services/resolution.py`, DB + gates) :
  définition effective via le resolver P2 (shadowing, lock/active, source
  de vérité inchangée), versions et liens chargés après filtre de
  visibilité, candidats runtime via `load_candidates` P4 (validation
  explicite des overrides session, liveness des choix stockés).
- Cœur pur (`studio_contracts/resolution.py`) : snapshot déjà chargé et
  déjà autorisé en entrée, `ResolvedAgentDefinition` ou `ResolutionFailure`
  en sortie. Aucune requête SQL, aucun HTTP, aucune machine, aucun
  provider, aucun LLM, aucun secret, aucune horloge, aucune dépendance
  FastAPI/dashboard. Testable entièrement en mémoire.
- Le cœur suppose les gates franchis en amont ; l'adaptateur préserve les
  règles fail-closed existantes (mapping §7).

## 2. Résultat canonique

`ResolvedAgentDefinition` : agent résolu (version exacte + provenance),
rules et skills résolues (versions exactes + provenance), model_profile
0..1 + `CapabilityRequirement` exacte (aucune exigence implicite sans
profil), références `composes_agent`/`references_workflow` préservées sans
expansion, runtime sélectionné + niveau gagnant + verdict de
compatibilité. Entrée stable future pour P7/P8/P9/P10, non implémentés
ici.

## 3. Résolution Library (MVP logique)

- Racine : sélection P2 réutilisée, jamais réimplémentée ; version
  explicitement identifiée (`lock`/`active`).
- Pins exacts `(UUID + version)` : jamais de substitution silencieuse vers
  une version active plus récente ; origine `pin` (membre additif de
  `VersionOrigin`, émis uniquement par la sortie P5).
- Seule transitivité implémentée : `skill → rule` (`refines_skill_rule`),
  exactement un niveau, car seule sémantique définie (DEC-0067).
  `composes_agent` et `references_workflow` sont préservés avec identité,
  version et provenance, sans sémantique d'exécution (workflows : P11 ;
  composition : sémantique non définie).
- Déduplication : même rule par plusieurs chemins = un objet logique +
  un `RulePath` par chemin (aucune provenance perdue). Même ressource
  épinglée à deux versions = `invalid_resolution_input` (fail-closed).

## 4. Précédence unique et partagée

`select_runtime` (`studio_contracts`) est l'unique implémentation de
l'ordre `session > project_override > user > project_default >
studio_default`, clé agent avant clé profil à niveau égal (sémantique
DEC-0068 vérifiée avant figeage). `resolve_runtime` P4 est refactoré
dessus via `load_candidates` partagé : sélection et verdict observables
inchangés (suite P4 verte) — le chargement ne court-circuite plus (tous
les overrides session sont validés explicitement avant sélection ; un
doublon incohérent, impossible via les unicités, échouerait fort en 500
plutôt qu'en premier-match silencieux). Aucune source de vérité
concurrente.

## 5. Compatibilité stricte, aucun fallback silencieux

Sélection puis jugement, jamais `search until compatible` :
`selection → compatibility → success | structured incompatibility`.
Un binding explicitement sélectionné mais incompatible (y compris override
session) produit `runtime_incompatible`, sans essayer aucun niveau
inférieur. `check_compatibility` inchangé (`unknown != compatible`).
Distinction stricte : aucun binding (`runtime = null`, résultat valide) vs
incompatible (erreur) vs cible devenue invalide (niveau traversé au
chargement, jamais d'erreur dure — sémantique P4 conservée).

## 6. Provenance structurée

`Provenance` (données, jamais de phrases) : `source`
(`active_pointer`/`project_lock`/`version_pin`/`runtime_binding`/
`session_override`), `resource_id`, `stable_key`, `scope`, `version`,
`version_origin`, `locked`, `relation`, `binding_level`, `via`.
Répond : pourquoi cette définition/version/rule/skill/profil, quel scope
a gagné, quel lock, quel niveau d'override.

## 7. Erreurs

Vocabulaire fermé : `definition_not_found`, `unresolvable_dependency`,
`runtime_incompatible`, `invalid_resolution_input` (portés par
`ResolutionFailure`, sans HTTP). Mapping public : dépendances →
`404 definition_not_found` (non-oracle DEC-0065 §2, raisons internes
jamais exposées) ; `runtime_incompatible` → `422` avec niveau/clé/
`unsatisfied` (données visibles de l'appelant) ; entrée incohérente →
`422 invalid_resolution_input`.

## 8. Neutralités et frontières

Harness-neutral (aucune branche Claude/Code/Cursor/Continue) et
provider-neutral (`provider_ref`/`model_ref` opaques, aucun catalogue
vendor). Frontière P6 : aucun catalogue provider/modèle, aucune
discovery, aucun registre de harness, aucun polling, aucune détection —
`RuntimeCapabilities` reste une donnée d'entrée. P5 n'exécute rien : il
décrit l'agent qui devrait être exécuté, son contenu, sa cible et ses
raisons.

## 9. Déterminisme

Même snapshot ⇒ même résultat : itération ordonnée, aucune horloge,
aucun aléatoire, aucun réseau, aucun état global. Testé explicitement
(répétition + ordre de candidats permuté ⇒ résultat identique).

## 10. Durcissement contractuel

Additif, même catégorie que DEC-0025/DEC-0036/DEC-0066 §6 : nouveau module
sans consommateur préalable, membre `pin` ajouté à `VersionOrigin`
(`LibraryResolution` P2 inchangée), nouveaux codes sur des chemins sans
endpoint public (exposition P7/P8). Pas de bump, par exemption
documentée : aucun consommateur conforme hors tests (vérifié :
`packages/studio-client` sans code Library, `services/mcp` sans outil
Library, `dashboard/src` sans consommation des routes Library). Durcit
P4 sur un point : l'incompatibilité choisie devient une erreur
(`runtime_incompatible`) au lieu d'un rapport (`compatible=false`) —
P4 stocké/rapporté inchangé, seule la couche P5 juge strictement.
