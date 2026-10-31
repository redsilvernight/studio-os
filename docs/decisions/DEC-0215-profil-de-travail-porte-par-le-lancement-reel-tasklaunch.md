---
id: DEC-0215
title: Profil de travail porté par le lancement réel (TaskLaunch.profile_key / profile
  pin)
status: accepted
date: '2026-10-15'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0215 — Profil de travail porté par le lancement réel (TaskLaunch.profile_key / profile pin)

Contexte : P04-gate bloquée, aucun lancement réel ne porte de profil (resolver daemon sans profile, TaskLaunchCreate sans champ) ; enforce_profile et la capture de pin ne servent qu'en tests.

Décision (additive) :
- TaskLaunchCreate.profile_key optionnel (clé de REFERENCE_PROFILES), exige agent_stable_key ; clé inconnue → 422 ; machine cible sans capacité launch_profiles → refus explicite.
- Le serveur calcule à la création le pin LaunchProfilePin (reference_work_profile + profile_elements de la définition résolue) et le stocke ; TaskLaunch.profile omis de la sérialisation quand absent (daemon N-1 inchangé pour un lancement sans profil).
- MachineCapabilities.launch_profiles : le daemon l'annonce ; le serveur ne cible un lancement profilé que vers une machine qui l'annonce.
- Le daemon recalcule le pin au démarrage via le resolver commun, construit LaunchProfile et applique enforce_profile (autorité locale, échec fermé) ; le snapshot enregistre preview/applied.
- Retry : hérite de profile_key, pin recalculé à la création de la nouvelle tentative.
Ordre de déploiement : Bloc A avant Bloc B (extra=forbid sur les capacités).
Hors périmètre : sélecteur de profil dans le dashboard, profils éditables (seuls les profils de référence).
