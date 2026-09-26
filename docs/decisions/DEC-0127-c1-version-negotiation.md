---
id: DEC-0127
title: 'C1 — Négociation de version client/serveur additive (/version, headers, 426)'
status: proposed
date: '2026-09-26'
superseded_by: null
---

# DEC-0127 — Négociation de version client/serveur additive

Le serveur expose `GET /version` (sans Bearer, `VersionInfo` :
`api_version`, `server_version`, `minimum_supported`/`latest` par famille
`desktop`/`daemon`/`dashboard`) et lit les headers optionnels
`X-Studio-Client` + `X-Studio-Client-Version` sur `/api/v1` : un build
déclaré sous le minimum familial reçoit `426 client_upgrade_required`
avec invitation à mettre à jour, flux d'auth inclus. Absence de headers,
famille inconnue ou version illisible = pass-through, les clients pré-C1
continuent de fonctionner sans modification.

Fenêtre de grâce (obligatoire vs recommandé) : un build déclaré entre le
minimum et la dernière version connue est **servi normalement** et marqué
sur la réponse par `X-Studio-Client-Update: recommended` +
`X-Studio-Client-Latest` (exposés en CORS), jamais bloqué. Le client
affiche alors un bandeau non bloquant (dashboard/Desktop) ou une note
stderr (CLI) ; seul le 426 déclenche l'écran bloquant. Le client Python
(`studio-client`, famille `daemon`) envoie ses headers sur chaque appel,
expose `update_recommended`/`latest_version` et `server_version()`, et
mappe `426` à `ClientUpgradeRequiredError`, jamais retenté.

Aucune promesse de signature de code : la distribution Windows est non
signée (DEC-0129), l'écran de mise à jour n'évoque donc jamais
Authenticode — la confiance vient des signatures minisign de l'updater.
