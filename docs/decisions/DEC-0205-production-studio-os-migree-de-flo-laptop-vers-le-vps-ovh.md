---
id: DEC-0205
title: Production Studio OS migrée de Flo-laptop vers le VPS OVH (flosrent.fr)
status: accepted
date: '2026-10-11'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0205 — Production Studio OS migrée de Flo-laptop vers le VPS OVH (flosrent.fr)

Statut : proposed.

Contexte : la production Studio OS tournait sur Flo-laptop (Docker Desktop, exposée par Tailscale sur flo-laptop.tailf61f85.ts.net, déployée par la tâche StudioOS-DeployPoll depuis deploy/flo-laptop).

Décision : la production passe sur le VPS OVH ubuntu@57.131.136.131 (Ubuntu 26.04, 4 vCPU, 7,6 Go).
- Branche de déploiement deploy/ovh-vps = master + couche VPS : Caddy avec TLS Let's Encrypt (ACME_EMAIL=contact@binaweb.fr), sans les écouteurs Tailscale :80 et :9000.
- Domaines : api.flosrent.fr, mcp.flosrent.fr, storage.flosrent.fr, studio.flosrent.fr (enregistrements A dans la zone OVH).
- Pare-feu ufw : ports 22, 80 et 443 seulement.
- Données migrées le 2026-10-11 : pg_dump -Fc et archive MinIO finaux pris après l'arrêt du laptop, sha256 vérifiés, Alembic 0029. STUDIO_JWT_SECRET et la configuration SMTP sont repris, donc les jetons existants restent valides.

Rollback : la stack du laptop est arrêtée mais pas supprimée et DeployPoll est désactivé. Pour revenir : `docker compose -p studio-os start`, puis réactiver la tâche, puis repointer les clients.

Conséquences : les clients pointent sur https://studio.flosrent.fr et https://mcp.flosrent.fr/mcp. L'installeur Desktop flo-laptop (storage :8443) est obsolète. deploy/flo-laptop n'est plus la cible de production.
