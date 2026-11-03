---
id: DEC-0235
title: 'Lancements : édition protégée par défaut et autorisation de production par
  session humaine'
status: accepted
date: '2026-10-24'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0235 — Lancements : édition protégée par défaut et autorisation de production par session humaine

Proposition d'implémentation du ticket fa864f0d : chaque nouveau lancement exige une machine annonçant launch_safety=true ; allow_production=false par défaut, persisté dans TaskLaunch. L'activation true exige une authentification dashboard JWT (jamais un jeton machine/MCP/credential de lancement) et une confirmation UI pour ce lancement seulement. Retry/replay ne réutilisent jamais une autorisation production. Le daemon retire les outils d'exécution et borne l'édition au workspace (Claude --restricted et whitelist --tools ; un harnais ne garantissant pas ce mode refuse avant démarrage). Le profil lecture seule reste plus restrictif, même avec autorisation. L'autorisation ne contourne jamais les autres garde-fous/profils/sandbox locaux. Les anciennes machines ne reçoivent pas les lancements protégés ; il faut mettre à jour leur daemon. La nouvelle exigence de capability est une évolution explicitement versionnée de l'admission du contrat API v1. Tests attendus : défaut sûr, aucune production via MCP, persistance/idempotence, retry sans héritage, commande adversariale non exécutée et handoff blocked. Raison : un prompt ou une blacklist shell n'est pas une frontière d'exécution.
