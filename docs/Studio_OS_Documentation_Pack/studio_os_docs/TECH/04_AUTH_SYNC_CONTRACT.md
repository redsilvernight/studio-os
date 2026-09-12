# Auth & Sync Contract

## Identites
- User identity
- Machine identity
- Agent identity

Une machine possede son propre credential revocable. Les agents peuvent heriter d'un contexte machine mais doivent garder leur identite logique.

## Roles minimum
admin, developer, agent, readonly.

## Synchronisation
Chaque ecriture offline-safe transporte un UUID stable et, si approprie, une Idempotency-Key. Le serveur garantit qu'un replay identique ne cree pas un doublon.

## Heartbeat
Intervalle nominal: 30 s. Etat derive de `last_seen_at` avec seuils configurables.

## Conflits de mise a jour
Les objets mutables utilisent `updated_at` et idealement une version entiere. En cas de conflit, le client doit recevoir 409 avec la version serveur courante.

## Offline
La queue locale SQLite conserve payload, event_id, tentative, prochaine tentative, statut et erreur. Backoff exponentiel borne. Les actions critiques non rejouables doivent etre marquees explicitement.
