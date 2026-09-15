---
id: DEC-0022
title: 'Etape 4.5 (validation docker-compose sur base vierge) fermee : chaine complete
  demontree'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:bf9322637138246518e70cf2240579a6c29112e384bc0451a3857854287873a6
---

# DEC-0022 — Etape 4.5 (validation docker-compose sur base vierge) fermee : chaine complete demontree

### Probleme

DEC-0021 laissait un ecart connu : la restauration disaster-recovery n'avait
ete demontree que sur une base/bucket isoles par nom, jamais sur un
environnement Postgres/MinIO reellement vierge (pas de conteneur, pas de
volume, pas de repertoire `docker/.data/`). Sous-etape 4.5 de
`docs/ROADMAP_STEP4_BREAKDOWN.md` : derniere case ouverte de l'etape 4.

### Decision

Rejouer reellement la sequence complete decrite par la sous-etape 4.5 contre
`docker/docker-compose.yml`, sans raccourci :

1. `docker compose down -v` + suppression de `docker/.data/` (conteneurs,
   volumes nommes `caddy_data`/`caddy_config`, bind mounts Postgres/MinIO —
   etat 100% vierge, verifie par absence de conteneurs et de repertoire
   avant demarrage).
2. `docker compose up -d --build` : build image `docker-api`/`docker-mcp`,
   demarrage des 5 services, tous `healthy`/`running` sans intervention.
3. `alembic upgrade head` execute manuellement depuis
   `services/api/` dans le conteneur `api` (toujours pas de migration
   automatique au demarrage, memes principes que DEC-0011/DEC-0018) : les 4
   revisions (`0001`→`0004`) s'appliquent en sequence sur une base
   strictement vide.
4. Bootstrap reel via `studio-admin` : `bootstrap-admin` (premier
   utilisateur admin) puis `machine create` (token machine), aucun des deux
   n'existait avant cette execution.
5. Appel authentifie `GET /api/v1/projects` a travers Caddy HTTPS
   (`https://localhost/`, certificat local Caddy) → `200 []` sur base
   fraichement migree.
6. Chaine fonctionnelle complete exercee avec des donnees reelles creees
   pendant cette session (pas de fixture rejouee) :
   - Projet cree (`POST /api/v1/projects`).
   - Realtime (DEC-0018) : flux SSE ouvert sur `GET
     /api/v1/events/stream?project=...` depuis l'interieur du conteneur
     `api` (bypass Caddy, `httpx` absent de l'image prod --no-dev ; lecteur
     Python `urllib` ecrit pour l'occasion) ; un evenement poste en
     parallele sur `POST /api/v1/events` apparait immediatement sur le flux
     ouvert (`id: 1`, meme `event_id`, meme payload) — reprise/curseur `seq`
     confirmee en conditions reelles, pas seulement par les tests unitaires
     existants.
   - Transferts + quotas (DEC-0019) : transfert cree, `GET
     /transfers/consumption?project_id=...` reflete correctement les octets
     consommes par projet (`consumed_bytes` passe de 0 a la taille du
     transfert).
   - Worker d'expiration (DEC-0020) : `expires_at` force dans le passe par
     SQL direct (meme methode que `tests/api/test_transfers_expiration.py`),
     `studio-admin transfers expire` supprime la ligne DB (objet jamais
     uploade dans MinIO — le worker ne bloque pas dessus) ; deuxieme
     execution immediate → `0 transfer(s) deleted` (idempotence confirmee en
     reel, pas seulement par la suite pytest).
   - Sauvegarde/restauration (DEC-0021) : `docker/backup.sh` execute contre
     cette instance (projet + 3 taches + 1 evenement en base), puis
     **teardown complet et reel** (`docker compose down -v` +
     suppression de `docker/.data/`), puis `docker compose up -d postgres
     minio minio-init` sur un environnement de nouveau strictement vierge,
     puis `docker/restore.sh` sans aucune migration Alembic rejouee (le
     dump porte deja `alembic_version=0004`). Verifie apres redemarrage
     `api`/`mcp`/`caddy` : `alembic_version` = `0004`, comptages
     `projects`/`tasks`/`events` identiques a la source (1/3/1), appel
     authentifie `GET /api/v1/projects` a travers Caddy retrouve exactement
     le projet cree avant le backup, avec le meme token machine (donc la
     table `machines` a bien survecu au cycle backup/restore). Ceci ferme
     l'ecart residuel de DEC-0021 : la chaine bootstrap + migration +
     sauvegarde + restauration a ete demontree sur un environnement
     veritablement vierge, pas seulement isole par nom de base/bucket.
7. Nettoyage final : `docker compose down -v` + suppression de
   `docker/.data/` et des fichiers de backup temporaires — aucun service
   Docker laisse tournant sur cette machine de dev apres la session, comme
   DEC-0014.

### Consequences

- Aucun changement de code ni de contrat : cette sous-etape est une
  validation d'integration, pas une implementation. `contract-guardian` non
  requis.
- Deux limites operationnelles reperees pendant l'execution, notees ici
  plutot que corrigees (hors perimetre d'une validation) :
  - `docker compose exec`/`run` avec un chemin absolu Unix (`-w
    /app/services/api`, `-v /backup:...`) exige `MSYS_NO_PATHCONV=1` sous
    Git Bash/MSYS (Windows) pour eviter la reecriture automatique du chemin
    en chemin Windows — deja anticipe dans `backup.sh`/`restore.sh`
    (`export MSYS_NO_PATHCONV=1` en tete de script) mais pas dans les
    commandes `alembic`/`studio-admin` lancees manuellement ; a documenter
    si une procedure d'exploitation Windows est un jour ecrite.
  - L'image `api`/`mcp` (`uv sync --frozen --no-dev`) n'embarque pas
    `httpx` : verifier un flux SSE depuis l'interieur du conteneur demande
    un client HTTP de la stdlib (`urllib`), pas `httpx` comme dans les tests
    (`ASGITransport`) — sans impact contractuel, note pour la prochaine
    verification manuelle du realtime en conteneur.
- `docs/ROADMAP_STEP4_BREAKDOWN.md` : sous-etape 4.5 marquee CLOS, etape 4
  entierement close (4.1 a 4.5). `docs/ROADMAP_CORRECTIONS_AUDIT.md` : etape
  4 consideree terminee.

### Validation independante (`studio-tester`, 2026-09-13)

Verdict : valide, aucune divergence. Sequence entierement rejouee de facon
independante (Tier 3, offline/idempotence explicitement vises), en repartant
d'un etat verifie vierge (`docker compose ps -a` vide, `docker/.data/`
absent avant de commencer) : build+up des 5 services, migration manuelle
`0001→0004`, bootstrap admin/machine, appel authentifie a travers Caddy,
puis chaine fonctionnelle complete avec ses propres donnees (projet, 3
taches, evenement SSE recu en direct avec meme `event_id`/`seq`, quota
passe de 0 a 1 Mio puis revenu a 0 apres expiration, worker d'expiration
idempotent). Cycle backup/restore rejoue independamment sur un
Postgres/MinIO de nouveau strictement vierge : comptages identiques (1
projet/3 taches/1 evenement), `alembic_version=0004`, meme token machine
fonctionnel a travers Caddy apres restauration. Les deux limites
operationnelles notees ci-dessus (reecriture de chemin MSYS,
absence de `httpx` dans l'image `--no-dev`) confirmees a l'identique et
contournees de la meme facon. Machine remise a l'etat vierge en fin de
validation (verifie).

### Preuves

Execution reelle le 2026-09-13, machine de developpement locale (Docker
Desktop, WSL2), stack `docker/docker-compose.yml` (Postgres 16 + MinIO +
API + MCP + Caddy), aucune image modifiee. Sequence complete rejouee dans
l'ordre decrit ci-dessus ; aucune etape sautee ni supposee.
