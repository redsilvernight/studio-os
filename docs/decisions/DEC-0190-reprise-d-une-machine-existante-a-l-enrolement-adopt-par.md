---
id: DEC-0190
title: Reprise d'une machine existante à l'enrôlement (adopt) par rotation de credential
status: accepted
date: '2026-10-06'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0190 — Reprise d'une machine existante à l'enrôlement (adopt) par rotation de credential

Statut : proposed. Quand le poste a déjà une machine, l'enrôlement ne crée plus de doublon : POST /api/v1/machines/{machine_id}/adopt (additif, scope own) fait tourner le credential (credential_hash) en gardant l'id et l'historique ; l'ancien credential est invalidé immédiatement ; machine révoquée → 409 ; machine d'un autre utilisateur/inexistante → 404 identique ; agent → 403. Côté client local : champ optionnel IdentityEnrollRequest.adopt_machine_id. Commande admin merge-machines --from --into (dry-run par défaut) pour fusionner les doublons existants. Source : docs/Studio_OS_Documentation_Pack/studio_os_docs/TECH/02_API_CONTRACT.md (entrée POST /machines/{machine_id}/adopt). Revue contract-guardian : additif, aucun bump de version. Reste à faire : écran dashboard « reprendre la machine X ».
