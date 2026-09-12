# Test & Acceptance Plan

## Tests backend
Auth, permissions, heartbeats, offline detection, task lifecycle, claim TTL, overlap detection, decisions, event idempotency, AI work, ProjectState, MCP.

## Tests transfer
- fichier 1 Ko.
- fichier 1 Go multipart.
- interruption a 50% puis reprise.
- URL signee expiree.
- mauvais hash.
- quota depasse.
- suppression et expiration.
- download avec Range.

## Tests clients
Daemon restart, queue persistante, reconnection, Git/Godot watcher, CLI, Graphify/Obsidian adapters, recording markers.

## Tests bout-en-bout
Deux machines simulees sur reseaux differents, une tache par machine, claims concurrents, AIWorkLog, transfert de fichier, coupure reseau, reprise, review et resume quotidien.

## Definition de done globale
Un nouveau poste peut etre configure sans modifier le serveur. Les deux developpeurs travaillent simultanement sans LAN commun. Les agents peuvent charger le contexte via MCP. Les gros transferts reprennent apres coupure. Les donnees privees restent locales. Le systeme est sauvegardable et restaurable.
