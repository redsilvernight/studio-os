---
id: DEC-0206
title: Desktop Prod construit depuis deploy/ovh-vps (remplace DEC-0162)
status: accepted
date: '2026-10-11'
supersedes:
- DEC-0162
superseded_by: []
source: server-export
---

# DEC-0206 — Desktop Prod construit depuis deploy/ovh-vps (remplace DEC-0162)

Décision utilisateur du 2026-10-11, suite à la migration de production vers le VPS OVH (DEC-0205). Reprend DEC-0162 à l'identique, sauf pour la branche et l'origine Prod.

- desktop-dev : construit depuis dev, identité Studi'OS Desktop Dev, origine locale loopback (inchangé).
- desktop-prod : construit depuis deploy/ovh-vps (au lieu de deploy/flo-laptop), identité Studi'OS Desktop, origines HTTPS https://studio.flosrent.fr (API) et https://storage.flosrent.fr (stockage), lues depuis les variables de l'environnement GitHub desktop-prod.
- Les deux tags/releases restent vivants et publiés sans suppression préalable ; pas de promotion croisée d'artefact entre canaux (DEC-0137 reste remplacée pour les canaux vivants) ; les rollbacks réutilisent uniquement un artefact antérieur du même canal.

Mise en œuvre : redsilvernight/studio-os#129 (desktop-channels.yml, ci.yml, build-policy.test.mjs).
