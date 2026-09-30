---
id: DEC-0168
title: 'AIB-D : loader runtime fusion .agents/ projet + Library, source injectee'
status: proposed
date: '2026-09-30'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0168 — AIB-D : loader runtime fusion `.agents/` projet + Library, source injectée

Tranche P4 (tâche `13da8354`). Répond à la question MISSING de la roadmap
P4 : « décider si le loader `.agents/` (`build_offline_resolved(repo_root, …)`,
instantané d'écriture, pas version-truthful) sert au runtime d'un autre
dépôt » — oui, comme **source projet** d'une fusion, jamais seul.

## Proposition

`build_offline_resolved` reste inchangé (instantané d'écriture, appelants P3
inchangés). Nouveau `build_merged_resolved(repo_root, stable_key, *,
library: LibrarySnapshot | None)` :

- `library=None` : strictement hors ligne, identique à `build_offline_resolved` ;
- `library` fournie : fusion par pièce — le fichier projet `.agents/`
  gagne quand il existe (surcharge projet prioritaire), l'entrée Library
  comble sinon (dépôt presque vide = manifest + blocs gérés résout les
  ressources studio) ; absent des deux côtés : même erreur que le chemin
  hors ligne (échec fermé, jamais de repli silencieux) ;
- provenance : les pièces Library portent `resource_id` / version /
  `version_origin` réels du snapshot ; les pièces fichier gardent l'espace
  uuid5 existant, explicitement non version-truthful ;
- clés fichier-only (`instructions`, `triggers`, `edit_policy`, `tools`) :
  fichier projet quand il existe, défauts sinon — la Library ne les porte
  jamais (`extra="forbid"`, conséquence documentée de DEC-0146).

`LibrarySnapshot.from_resolved(ResolvedAgentDefinition)` construit le
snapshot depuis `POST /api/v1/resolutions` (lecture pure existante, aucun
nouvel endpoint, aucun changement de contrat) ; `canonical.py` reste pur
(aucun réseau : le snapshot est pré-récupéré par l'appelant). CLI :
`adapters export --from-canonical --with-library` (et `adapters check`),
`--project-id` optionnel en passthrough (précédences et locks côté
serveur) ; serveur injoignable = erreur, jamais de repli hors ligne
silencieux.

## Alternatives rejetées

- Second moteur de résolution côté client : interdit par DEC-0144 (la
  fusion réutilise la forme `resolve_full`, ne re-décide aucune version).
- Copie des contenus `studio-*` dans le dépôt : interdit par DEC-0146
  (servis à la demande, seul le protocole est matérialisé).
- Faire du snapshot Library la source unique : casserait review/diff/
  anti-drift (le fichier gagne à l'écriture, la Library gagne à la
  résolution — cf. en-tête de `canonical.py`).

## Frontière

`to_publish_payload` et la commande de publication restent à la tâche
sœur `2c794311` (ne pas franchir).
