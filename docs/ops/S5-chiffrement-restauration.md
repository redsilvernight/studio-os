# S5 — Chiffrement au repos et restauration par studio

Statut : **plan d'exécution**. Ce document ne consigne aucune opération déjà
réalisée : rien n'a été lancé sur un serveur, aucun volume, bucket ou dump n'a
été chiffré, exporté ou restauré dans le cadre de cette tâche S5. Les commandes
ci-dessous sont à exécuter par un humain, sur l'hôte de l'instance, avec les
droits adéquats.

Périmètre :

- chiffrement au repos des données de l'instance (PostgreSQL, MinIO, sauvegardes,
  secrets d'exécution) ;
- sauvegarde et restauration **d'un studio** (périmètre logique), distinctes de
  la reprise après sinistre globale déjà couverte par `docker/backup.sh` et
  `docker/restore.sh`.

Hors périmètre : le code applicatif (cette tâche ne modifie ni schéma ni
migration). Les anti-abus d'inscription sont traités côté API dans
`registration_guard.py` et documentés séparément.

## 0. Décisions à prendre avant d'exécuter

À valider par l'exploitant, puis à consigner ici avec date et auteur :

1. **RPO / RTO** visés pour une instance et pour un studio isolé.
2. **Technique de chiffrement au repos** : volume chiffré au niveau hôte
   (LUKS), chiffrement côté MinIO (SSE-S3 ou SSE-KMS), ou les deux. Le
   chiffrement applicatif colonne par colonne (`pgcrypto`) n'est pas retenu par
   défaut : il casse les recherches et les index existants.
3. **Gestion des clés** : support (KMS managé, clé hôte protégée hors ligne,
   `age`/GPG), propriétaire, procédure de rotation et de révocation, coffre de
   la clé privée **hors de l'hôte sauvegardé**.
4. **Emplacement hors site** des sauvegardes chiffrées (le script
   `scripts/pull-offsite-backup.ps1` existe déjà côté poste ; confirmer la
   destination).
5. **Politique de rétention** et de destruction (le script de backup applique
   déjà un nombre de générations).

## 1. Inventaire à vérifier

Sur l'hôte, relever sans secret :

- volumes des données : `docker compose config --volumes`, puis le chemin réel
  de `./.data/postgres` et `./.data/minio` ;
- bucket applicatif : `STUDIO_S3_BUCKET` (défaut `studio-transfers`) ;
- sauvegardes : répertoire passé à `docker/backup.sh` et éventuel
  `STUDIO_INFRA_BACKUP_DIR` (mesure de taille seulement) ;
- secrets : `docker/.env` (mode, propriétaire), clés SMTP, `STUDIO_JWT_SECRET`,
  clés MinIO, secret webhook GitHub ;
- journaux applicatifs : vérifier qu'ils ne contiennent ni token ni mot de
  passe (le filtre `RedactingFilter` est en place côté API).

Preuve attendue : sortie d'inventaire datée, sans valeur de secret.

## 2. Chiffrement au repos

### 2.1 Volumes de données

1. Arrêter la pile (`docker compose stop api mcp dashboard`), pas les volumes.
2. Chiffrer le périphérique ou le volume hôte qui porte `./.data/postgres` et
   `./.data/minio` avec LUKS2 (`cryptsetup luksFormat`, `cryptsetup open`,
   système de fichiers, montage).
3. Monter automatiquement au démarrage sans exposer la phrase de passe dans un
   fichier en clair : clé dans le TPM/`crypttab` avec fichier de clé protégé, ou
   saisie manuelle assumée.
4. Redémarrer la pile et vérifier `lsblk -f` (type `crypto_LUKS` + montage),
   `cryptsetup status`, et l'accès applicatif (`GET /healthz`).

### 2.2 MinIO

Choisir **une** option, la consigner :

- SSE-S3 : MinIO chiffre avec sa clé interne ; activer le chiffrement par
  défaut du bucket (`mc encrypt set sse-s3 <alias>/<bucket>`) ;
- SSE-KMS : MinIO délègue à un KMS (KES/Vault) ; documenter l'endpoint, la clé
  et la procédure de rotation.

Vérification : déposer un objet de test, `mc stat` doit afficher l'algorithme
de chiffrement ; le retirer ensuite.

### 2.3 Sauvegardes

Les dumps `pg_dump` et les miroirs MinIO ne sont **pas** chiffrés par
`docker/backup.sh` : chiffrer l'archive après création, avant toute copie hors
site.

- Chiffrer chaque répertoire daté avec `age` (clé publique sur l'hôte, clé
  privée hors ligne) ou GPG.
- Ne jamais stocker la clé privée dans le même répertoire ni dans le même
  bucket que les archives.
- Test de restitution : déchiffrer une archive dans un répertoire temporaire et
  vérifier que `pg_restore --list` lit le dump.
- Refus attendu si la clé est absente : la restauration doit échouer, jamais
  silencieusement produire des données illisibles.

### 2.4 Secrets d'exécution

- `docker/.env` en `600`, propriétaire = compte d'exploitation, absent de Git.
- Les sauvegardes chiffrées ne doivent pas embarquer `.env` ; si les secrets
  doivent être sauvegardés, les traiter comme un secret distinct, chiffré et
  documenté.
- Rotation : JWT (déconnexion globale), clés MinIO, secrets SMTP et webhook.

## 3. Sauvegarde et restauration par studio

La sauvegarde existante est **globale** (toute l'instance). Restaurer un seul
studio demande un export logique ciblé, à construire sur les identifiants
`studio_id` du schéma.

### 3.1 Export d'un studio

1. Identifier le studio : `SELECT id, name FROM studios WHERE id = '<uuid>';`
2. Lister les tables portant la colonne `studio_id` (source de vérité : le
   schéma Alembic et `services/api/src/studio_api/db/models/`). Ne pas se fier à
   une liste figée dans ce document : elle doit être régénérée à chaque
   exécution.
3. Produire un export cohérent :
   - dump ciblé `pg_dump --data-only --table <table> --where "studio_id = '<uuid>'"`
     pour les tables portant `studio_id`, ou une série de `COPY (SELECT …) TO`
     dans une transaction `REPEATABLE READ` ;
   - inclure les lignes de référence strictement nécessaires (utilisateurs
     membres, machines, agents) en pseudonymisant ou en documentant le lien ;
   - ne pas exporter les secrets (tokens, hashes de mot de passe) sauf décision
     explicite et archive chiffrée dédiée.
4. Exporter les objets MinIO du studio : `mc mirror --overwrite
   <alias>/<bucket>/<préfixe-studio> ./export/minio`.
5. Archiver (`tar`), chiffrer (section 2.3), horodater (`YYYYMMDDTHHMMSSZ`),
   calculer une empreinte (`sha256sum`) et la consigner hors de l'archive.

### 3.2 Restauration d'un studio

1. Restaurer **d'abord** dans une instance vierge ou un studio de staging, jamais
   par-dessus un studio en production sans sauvegarde préalable vérifiée.
2. Créer le studio cible et noter son UUID ; ne pas réutiliser l'UUID source
   sans décision explicite (collisions de clés).
3. Réinjecter les lignes exportées en réécrivant `studio_id` vers l'UUID cible
   (script SQL de remap relu et testé), dans l'ordre des dépendances
   (studios → memberships → projets → tâches → …).
4. Restaurer les objets MinIO vers le préfixe du studio cible
   (`mc mirror --overwrite ./export/minio <alias>/<bucket>/<préfixe-cible>`).
5. Recalculer/réindexer ce que l'API dérive (recherche, graphe de code,
   projections de bibliothèque) via les commandes d'administration existantes,
   pas à la main en SQL.
6. Vérifier l'accès avec un compte de test membre du studio uniquement.

### 3.2b Script de restauration (livré)

`uv run python scripts/studio_restore.py <archive.zip> <email-du-propriétaire>`
restaure une archive d'export (`studio.export/v1`, déchiffrée) dans un **nouveau**
studio (nouveaux identifiants, propriétaire = le compte indiqué, autres membres
non recréés, références machines/agents/builds vidées). Prouvé par
`tests/api/test_studio_restore.py` (comptages et fichiers identiques, source
inchangée, archive étrangère refusée). Non prouvé : chiffrement des volumes et de
MinIO, chiffrement des archives, exercice sur un hôte de staging.

### 3.3 Vérifications après restauration

- Le studio restauré n'apparaît que pour ses membres ; aucun accès croisé avec
  un autre studio.
- Comptages avant/après par table exportée : identiques à la source.
- Objets MinIO : nombre et tailles identiques ; un transfert de test se
  télécharge.
- Aucune donnée d'un autre studio n'est visible (requête de contrôle par
  `studio_id` sur les tables exportées).
- `GET /healthz` vert, journaux sans erreur d'intégrité.
- Le studio source reste inchangé pendant toute l'opération.

## 4. Checklist de recette (à cocher avec preuve)

- [ ] Décisions RPO/RTO, technique de chiffrement et gestion des clés consignées.
- [ ] Volumes PostgreSQL et MinIO chiffrés, montage vérifié après redémarrage.
- [ ] Chiffrement MinIO actif (SSE) prouvé par `mc stat` sur un objet de test.
- [ ] Une sauvegarde datée est chiffrée et déchiffrable avec la clé hors ligne.
- [ ] `pg_restore --list` lit le dump déchiffré.
- [ ] Export d'un studio de test produit, chiffré, empreinte consignée.
- [ ] Restauration de cet export dans une instance de staging réussie.
- [ ] Comptages et objets MinIO identiques ; cloisonnement entre studios vérifié.
- [ ] RTO mesuré et noté.
- [ ] Rotation/absence de clé testée : la restauration échoue proprement.
- [ ] Aucun secret dans les archives, les journaux ou ce document.

## 5. Rollback

- Chiffrement des volumes : démonter, `cryptsetup close`, revenir au volume
  clair **uniquement** après restauration vérifiée depuis une sauvegarde
  chiffrée ; ne jamais supprimer la seule copie chiffrée avant validation.
- Restauration de studio : supprimer le studio de staging créé pour le test
  (données + préfixe MinIO), conserver l'archive et son empreinte.
- En cas de doute sur l'intégrité : arrêter la pile, conserver les volumes et
  journaux, escalader avant toute nouvelle écriture.

## 6. Références

- `docker/backup.sh`, `docker/restore.sh`, `docker/install-backup-cron.sh` :
  sauvegarde/restauration globale existantes (non chiffrées).
- `scripts/pull-offsite-backup.ps1` : copie hors site côté poste.
- `services/api/src/studio_api/settings.py` : `STUDIO_S3_BUCKET`,
  `STUDIO_INFRA_BACKUP_DIR`, secrets SMTP/JWT/MinIO.
- DEC-0106 : limites en mémoire mono-réplique et chaîne de confiance proxy.
