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

Le client Python (`studio-client`, famille `daemon`) envoie ses headers
sur chaque appel ; `426` est mappé à `ClientUpgradeRequiredError`,
jamais retenté. Changement classé additif : nouvel endpoint, nouveaux
headers optionnels, nouveau code d'erreur uniquement sur déclaration
explicite d'un vieux build. `TECH/02_API_CONTRACT.md` mis à jour dans
le même changement. L'affichage côté clients (recommandé vs obligatoire)
et la matrice de tests N-1/N relèvent des deux autres tâches C1.
