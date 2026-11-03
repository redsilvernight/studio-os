---
id: DEC-0198
title: Mission Control D3 — profils d'exécution composés, autorité locale finale
status: accepted
date: '2026-10-10'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0198 — Mission Control D3 — profils d'exécution composés, autorité locale finale

Gate P01-architecture-gate, acceptée par l'humain le 2026-10-10. Source : docs/mission-control/baseline.md §F.
Décision : un profil d'exécution compose les primitives existantes (Library, RuntimeBinding, ModelProfile, overrides de session) via le resolver commun ; aucune nouvelle couche indépendante de configuration ou d'autorisation. Précédence et versioning explicites, prévisualisation des valeurs effectives et de leur origine. Un profil serveur ne peut jamais étendre l'opt-in, l'allowlist ni les permissions locales : la machine (Bloc B) décide en dernier et échoue fermé.
Commun D1–D6 : voir D1.
Étapes dépendantes : P04-profile-contract, P04-profile-enforce, P04-gate.
