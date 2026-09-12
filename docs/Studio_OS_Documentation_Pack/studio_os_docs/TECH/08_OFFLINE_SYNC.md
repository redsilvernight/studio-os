# Offline Sync

## But
Permettre au developpeur de continuer a travailler si le VPS ou Internet devient temporairement inaccessible.

## Queue locale
SQLite avec tables pending_events, pending_mutations, pending_markers, sync_state et multipart_uploads.

## Regles
- Toutes les operations rejouables ont un UUID stable.
- Le serveur repond de maniere idempotente.
- Ordre preserve par session lorsque necessaire.
- Les timestamps client sont conserves mais le serveur ajoute son timestamp.
- Une operation rejetee definitivement passe en `dead_letter` et est visible.

## Transfers
Le multipart state conserve upload_id, object_key, parts terminees et ETags. Une coupure peut reprendre l'upload.
