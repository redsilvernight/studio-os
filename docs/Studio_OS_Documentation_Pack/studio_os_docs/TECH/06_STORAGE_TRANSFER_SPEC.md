# Studio Transfer / Storage Specification

## Objectif
Permettre l'echange de fichiers petits ou tres gros entre les deux developpeurs, avec contexte, reprise, integrite et expiration.

## Architecture
Studio API gere autorisation et metadonnees. MinIO/S3 stocke les octets. Le client upload/download directement via URLs pre-signees.

## Upload petit fichier
1. POST /transfers.
2. Client calcule le MD5 (base64, RFC 1864) du fichier.
3. POST /transfers/{id}/upload/initiate avec `content_md5` : l'API presigne
   le PUT avec ce Content-MD5 (DEC-0025) et le persiste sur le Transfer.
   Absent -> `422 missing_content_md5`. Rejoue sur un transfert deja `ready`
   -> `409 transfer_already_ready`.
4. Client upload en envoyant l'entete `Content-MD5` — MinIO/S3 rejette le PUT
   (`BadDigest`) si les octets ne correspondent pas, sans jamais faire
   transiter les octets par l'API.
5. Client appelle complete avec taille/`sha256` (declaratif, non verifie).
   La taille declaree doit correspondre a `Transfer.size_bytes` fixe a la
   creation (celle verifiee contre le quota DEC-0019), pas seulement a
   l'objet reel — sinon `422 size_mismatch`.
6. Serveur verifie l'objet (`422 object_not_found` si jamais uploade),
   re-verifie taille + `content_md5` via `head_object` (defense en
   profondeur, `422 content_md5_mismatch` sinon) puis passe `ready`.

## Multipart gros fichier
1. Initiate multipart. La reponse porte `part_urls_expires_at` (DEC-0037,
   additif) — le client peut se refraichir avant meme un premier 403.
2. Client decoupe en chunks (recommande 64-128 MiB).
3. Chaque part est envoyee directement au storage.
4. Les ETag/parts sont persistes localement.
5. Reprise apres coupure sans recommencer les parts terminees.
6. Complete multipart puis validation taille (contre `Transfer.size_bytes`
   fixe a la creation) — le `sha256` declare reste non verifie cote serveur
   pour ce chemin (DEC-0025) ; l'integrite par-part reste appliquee de facon
   transitive par la verification d'ETag S3 native de
   `CompleteMultipartUpload`.

### Reprise apres expiration des URLs par-part (DEC-0037)

Un upload interrompu plus longtemps que la duree de vie des URLs presignees
(10-30 min) ne peut pas reprendre avec les URLs mises en cache — le serveur
ne persiste jamais l'`upload_id` en cours (aucune nouvelle table), donc
`POST /transfers/{id}/upload/refresh-parts` interroge `ListParts` sur le
storage lui-meme (verite authoritative) pour re-presigner uniquement les
parts encore manquantes et renvoie aussi les parts deja durablement acceptees
(`uploaded_parts`) — un client doit les adopter au lieu de les reenvoyer,
meme si son propre etat local les ignorait (ecriture SQLite perdue apres un
crash entre le PUT et l'enregistrement local). `upload_id` invalide/inconnu
de storage -> `409 unknown_upload_id` : le client purge son etat local et
relance `upload/initiate` (reupload complet, jamais un echec definitif).

Un upload multipart jamais complete et jamais repris reste sinon
indefiniment facturable dans le bucket — un worker de nettoyage
(`studio-admin transfers abort-stale-multipart --older-than-days N`, N=7 par
defaut, `STUDIO_MULTIPART_ABANDON_AFTER_DAYS`) abandonne (`AbortMultipartUpload`)
tout upload en cours plus vieux que ce delai, cote storage uniquement (age
`Initiated` de storage — seul signal disponible puisque le serveur ne
persiste pas cet etat). Un abandon n'est jamais une perte de donnees pour le
client : sa prochaine tentative recoit `409 unknown_upload_id` et repart d'un
`upload/initiate` frais. La suppression/expiration d'un transfert
(`DELETE`, worker d'expiration DEC-0020) abandonne aussi tout multipart
encore en cours sur son `object_key` avant de supprimer l'objet.

## Integrite (DEC-0025)
Seul `content_md5` (chemin single-PUT) est reellement verifie serveur : MinIO/
S3 refuse nativement tout mismatch au moment du PUT presigne, et
`complete_upload` re-verifie `head_object().ETag` en defense en profondeur.
`sha256` est une valeur declarative du client dans tous les cas — corroboree
indirectement par `content_md5` sur le chemin single-PUT, jamais verifiee sur
le chemin multipart (MinIO/S3 n'exposent pas de checksum d'objet complet via
URL pre-signee a un client sans identifiants AWS).

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
