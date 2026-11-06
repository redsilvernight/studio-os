---
kind: model_profile
stable_key: single-agent
scope: studio
description: "Profil par défaut d'un poste à un seul agent : codage, outils de fichiers et de shell, contexte large. Neutre vis-à-vis des fournisseurs."
requirements:
  reasoning: high
  coding: true
  context_window_min: 128000
  tools_required: [read, write, shell, search]
  local_compatible: false
---

Remplace l'ancien profil mono-fournisseur. Un seul modèle tient tous les rôles (`reader`, `worker`, `verifier`) ; les surcouches utilisateur peuvent déclarer des profils plus légers pour la lecture.
