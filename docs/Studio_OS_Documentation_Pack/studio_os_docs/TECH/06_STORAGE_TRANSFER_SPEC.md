# Studio Transfer / Storage Specification

## Objectif
Permettre l'echange de fichiers petits ou tres gros entre les deux developpeurs, avec contexte, reprise, integrite et expiration.

## Architecture
Studio API gere autorisation et metadonnees. MinIO/S3 stocke les octets. Le client upload/download directement via URLs pre-signees.

## Upload petit fichier
1. POST /transfers.
2. API cree Transfer.
3. API fournit URL pre-signee PUT.
4. Client upload.
5. Client appelle complete avec taille/hash.
6. Serveur verifie l'objet et passe `ready`.

## Multipart gros fichier
1. Initiate multipart.
2. Client decoupe en chunks (recommande 64-128 MiB).
3. Chaque part est envoyee directement au storage.
4. Les ETag/parts sont persistes localement.
5. Reprise apres coupure sans recommencer les parts terminees.
6. Complete multipart puis validation taille/hash.

## Download
URL GET pre-signee courte. Support HTTP Range pour reprise.

## Retention suggeree
- transfer temporaire: 7 jours.
- build: 30 jours.
- asset: manuel ou longue retention.
- recording brut: local par defaut.

## Securite
Bucket prive, URLs signees 10-30 min, quotas, taille max, noms non fiables, pas de chemin utilisateur direct dans object_key. Object key genere: `studio/{project}/{yyyy}/{mm}/{transfer_uuid}/{safe_name}`.

## UX
Dashboard drag/drop, progression, vitesse, ETA, pause/reprise, incoming/outgoing, suppression, contexte projet/tache. CLI `studio transfer send/list/incoming/outgoing/download/cancel/delete`.

## Stockage permanent
Studio Storage peut distinguer `temporary`, `build`, `asset`, `export`, `archive`. Les objets permanents doivent avoir retention explicite et etre visibles dans une vue de quota.
