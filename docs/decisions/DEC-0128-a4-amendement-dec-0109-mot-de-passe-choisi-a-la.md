---
id: DEC-0128
title: 'A4 — Amendement DEC-0109 : mot de passe choisi à la vérification, récupération
  indépendante du flag'
status: accepted
date: '2026-09-26'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0128 — A4 — Amendement DEC-0109 : mot de passe choisi à la vérification, récupération indépendante du flag

Statut : proposed (accord utilisateur requis). Amende DEC-0109.
Résumé : register ne prend que l'adresse ; mot de passe et display_name sont posés à verify-email par le détenteur de la boîte (supprime la pré-prise de compte et le texte tiers dans l'e-mail, relevés par contract-guardian). forgot/reset disponibles dès qu'un backend e-mail est configuré, indépendamment de STUDIO_PUBLIC_REGISTRATION_ENABLED ; un reset active un compte pending. Ajout de POST /auth/change-password (additif). Fournisseur e-mail disabled|file|smtp, secrets en env, démarrage refusé si configuration incohérente. Limites acceptées : écart de latence DB connu/inconnu (corps identique, e-mail après réponse) ; second e-mail possible après crash entre commit et complétion d'idempotence.
Fichier : docs/decisions/DU0-A-public-registration.md (section « Amendement A4 »).
