# DEC-0130 — Enrôlement du poste Desktop : une seule entrée secrète sur le pont local (amende DEC-0093)

Statut : `accepted` (option choisie puis acceptée explicitement par l'humain
le 2026-09-26 ; fichier et serveur alignés).

## Contexte

A5 exige qu'un utilisateur auto-inscrit enrôle sa machine Desktop sans
administrateur. L'API le permet (`POST /api/v1/machines` en libre-service,
tâche 1622a1db), mais le Desktop n'avait aucun chemin : le credential machine
vit dans le trousseau lu par le démon, la session humaine vit dans la
WebView, et DEC-0093 interdit toute valeur secrète sur le pont
`studio.local/v1`.

Options écartées : commande native Rust (deux écrivains du trousseau au
format à garder compatible), code d'enrôlement émis par le serveur (nouvel
endpoint + migration).

## Décision

1. Nouvelle commande `identity.enroll` (capacité `identity.enroll`,
   mutante, additive : offerte, jamais requise).
2. `IdentityEnrollRequest.human_session` est **la seule** entrée secrète
   autorisée à traverser le pont (`SECRET_INPUT_FIELDS`). Toute autre valeur
   secrète reste refusée par les gardes structurelles de DEC-0093.
3. Garde-fous :
   - `SecretStr` : masqué dans toute repr et tout dump ; écriture seule
     (jamais dans une réponse, un événement, une fixture) ;
   - `hide_input_in_errors` sur la requête, `BridgeRequest` et l'adaptateur
     de messages : une erreur de validation ne recopie jamais le payload ;
   - le démon vérifie que `profile.server_origin` est sa propre origine
     **avant** tout appel réseau (la session ne part jamais vers un autre
     serveur) ;
   - un seul `POST /api/v1/machines`, jamais rejoué, en-tête explicite (la
     variable d'environnement du jeton machine ne peut pas s'y substituer) ;
   - le credential retourné va dans le trousseau sous la clé lue par tous
     les clients (`KeyringTokenStore("studio-os")`, DEC-0024) ; un seul
     écrivain (Python) ;
   - refus à messages fixes (`details.reason` : `session_expired`,
     `forbidden`, `server_unreachable`, `server_refused`,
     `credential_not_stored`), jamais le texte du serveur ;
   - un credential présent n'est remplacé que sur `replace_existing`
     explicite (cas « révoqué »).
4. La réponse ne porte que l'issue, l'id de la machine et la vue d'identité.

## Conséquences

- Le jeton humain transite de la WebView au démon local (processus de
  l'utilisateur, sur son poste) ; il expire en 15 min au plus.
- Un démon compromis pourrait abuser de la session : exposition marginale,
  il détient déjà le credential machine.
- Les tests de contrat verrouillent l'exception (ensemble exact des champs
  secrets, jamais en réponse, masquage, erreurs sans écho) ; le démon est
  testé sur l'absence de fuite dans ses logs.

## Références

- Amende DEC-0093 (`docs/decisions/DEC-0093-*.md`, règle « only references
  cross the boundary »).
- Contrat : `docs/DESKTOP_P1_LOCAL_CONTRACTS.md`,
  `packages/studio-contracts/src/studio_contracts/local/identity.py`.
- Démon : `packages/studio-client/src/studio_client/daemon/enrollment.py`.
