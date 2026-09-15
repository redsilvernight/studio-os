---
id: DEC-0021
title: 'Sauvegarde Postgres/MinIO et restauration (roadmap etape 4.4) : scripts shell
  + pg_dump/pg_restore + mc mirror'
status: active
date: '2026-09-13'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:0f4a7179f212abaf7d659b061661b0eb1edf931c0dd49156cb9563266520aab5
graphify_entities:
- kind: file
  node_id: docker_backup
  path: docker/backup.sh
  project: studio-os
  relation: implements
  symbol: backup.sh
- kind: file
  node_id: docker_restore
  path: docker/restore.sh
  project: studio-os
  relation: implements
  symbol: restore.sh
---

# DEC-0021 — Sauvegarde Postgres/MinIO et restauration (roadmap etape 4.4) : scripts shell + pg_dump/pg_restore + mc mirror

### Probleme

Aucune procedure de sauvegarde/restauration n'existait pour la stack
`docker/docker-compose.yml` (derniere case ouverte de la definition de done
du Bloc A cote Cloud/Core, sous-etape 4.4 de
`docs/ROADMAP_STEP4_BREAKDOWN.md`).

### Decision

- Mecanisme : deux scripts shell (`docker/backup.sh`, `docker/restore.sh`),
  a declencher par un cron VPS documente au deploiement — meme choix que le
  worker d'expiration des transferts (DEC-0020) : pas de scheduler
  in-process, pas de dependance non demandee par un contrat.
- Postgres : `pg_dump --format=custom` (dump binaire compresse, restaurable
  avec `pg_restore --clean --if-exists`). Le dump embarque le schema complet
  (y compris `alembic_version`) tel qu'il existait au moment de la
  sauvegarde : `restore.sh` ne relance donc pas les migrations Alembic avant
  de restaurer — il suppose un Postgres neuf et vide, et le dump recree tout
  lui-meme. Consequence assumee : si le code a avance (nouvelles migrations)
  entre la sauvegarde et la restauration, la base restauree reste a l'etat
  du dump ; rejouer les migrations posterieures reste une etape manuelle
  separee, non couverte par ce script.
- MinIO : `mc mirror` (conteneur `mc` ephemere sur le reseau compose, jamais
  de dependance a un binaire `mc` installe sur l'hote) entre le bucket et un
  repertoire hote horodate.
- Retention : `backup.sh` accepte un nombre de sauvegardes a conserver
  (defaut 7) et supprime les plus anciennes apres une sauvegarde reussie
  uniquement (jamais avant, pour ne pas perdre une sauvegarde valide si la
  nouvelle echoue).
- Emplacement des scripts : `docker/` (aux cotes de `docker-compose.yml` et
  `Caddyfile`), pas `services/api/` — ce sont des scripts d'exploitation de
  la stack compose, pas du code d'application.

### Preuve de restauration reelle (2026-09-13)

Execution reelle contre la stack `docker/docker-compose.yml` locale
(Postgres 16 + MinIO, memes images que la CI), avec une ligne `projects`
marqueur (`slug=backup-restore-marker`) et un objet `marker.txt` inseres
prealablement dans le bucket `studio-transfers` :

1. `docker/backup.sh` execute avec succes : `studio.dump` (29 647 octets,
   schema + donnees) et `minio/marker.txt` produits sous un repertoire
   horodate ; deuxieme execution verifiee pour la purge par retention (pas
   de suppression tant que le nombre de sauvegardes reste sous la limite).
2. Restauration verifiee dans un environnement isole (base Postgres
   `studio_restore_test` et bucket `studio-transfers-restore-test` distincts
   de l'environnement de developpement, pour ne pas ecraser destructivement
   les donnees locales existantes sans confirmation explicite — la procedure
   `restore.sh` documentee, elle, cible directement `postgres`/`minio` de la
   stack sur un environnement neuf/vide, ce qui est le cas reel en
   restauration disaster-recovery) :
   - `pg_restore -d studio_restore_test --no-owner studio.dump` : 13 tables
     recreees, ligne marqueur `backup-restore-marker` retrouvee intacte
     (`slug`, `name`, `description` identiques).
   - `mc mirror /backup local/studio-transfers-restore-test` : `marker.txt`
     retrouve avec son contenu exact (`mc cat`).
3. Nettoyage : base et bucket de test supprimes, marqueurs de developpement
   retires (`DELETE`/`mc rm`), stack repassee a l'etat arret initial
   (`docker compose stop`) — aucune donnee de developpement perdue par ce
   test.

Classification contrat : aucune. Scripts d'exploitation externes a l'API,
aucun endpoint, evenement ou schema modifie.

### Ecart connu, non introduit par cette sous-etape

`restore.sh` documente un flux "Postgres/MinIO neufs et vides" ; le disaster
recovery reel sur un poste neuf (etape 4.5, validation Docker Compose sur
base vierge) reste a executer pour prouver l'enchainement complet
bootstrap + migration + restauration sur un environnement veritablement
vierge, pas seulement isole par nom de base/bucket.

### Validation independante (`studio-tester`, 2026-09-13)

Verdict : valide, avec reserves mineures non bloquantes. Restauration
rejouee independamment via le point d'entree reel de `restore.sh` (pas une
reimplementation manuelle), avec un nom de base/bucket different
(`studio_restore_qa`/`studio-transfers-restore-qa`) : 13 tables, comptages
`projects/transfers/events` identiques source/restaure, objet marqueur
relu avec contenu exact. Purge par retention revalidee sur deux executions
successives. Aucun ecart trouve entre DEC-0021 et le code reellement
execute. Reserves consignees comme notes d'exploitation (pas de correctif
de code requis) :

- `mc alias set` passe les secrets MinIO en argument CLI du conteneur
  ephemere (visibles via `docker top`/`ps` le temps de l'execution) — meme
  pattern deja present dans `minio-init`, pas une regression introduite ici.
- La purge de retention suppose que `BACKUP_ROOT` ne contient que des
  repertoires de sauvegarde horodates : a utiliser avec un repertoire dedie
  sur le VPS, jamais partage avec d'autres usages.
- Comme pour le worker d'expiration (DEC-0020) : pas de verrou anti-
  chevauchement (`flock`) entre deux executions cron qui se recouperaient —
  a documenter au deploiement si la cadence choisie le justifie.

### Preuves

`docker/backup.sh`, `docker/restore.sh` — testes en reel le 2026-09-13
contre Postgres 16 + MinIO (mc `quay.io/minio/mc:latest`) locaux, memes
images que la CI/docker-compose ; revalides independamment par
`studio-tester` le meme jour.
