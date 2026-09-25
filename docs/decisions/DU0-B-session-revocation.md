---
title: "DU-0/B — JWT court et version de révocation"
status: active
server_decision_id: 4e509c7d-0a0c-4661-b97f-ffcbe916e5b9
server_readable_id: DEC-0110
server_replaces: 14905c34-04d6-4803-8723-ed4bb75ae555 (DEC-0105, superseded) ; b02d4215-857b-4b0b-b2fc-a1426a07b57a (DEC-0099, superseded)
---

# DU-0/B — JWT court et version de révocation

## Current

Le Dashboard garde en mémoire un JWT HS256 de 480 minutes. Ses claims de rôle
et d'email ne sont pas réévalués et le JWT ne possède pas de mécanisme propre
de révocation. Les credentials machine/MCP opaques sont déjà hashés et
révocables.

## Options

1. JWT long inchangé : rejeté.
2. Access JWT et refresh token rotatif : différé, car il ajoute une famille de
   secrets persistés et sa rotation.
3. Access JWT court et compteur de révocation : recommandé pour V1.

## Proposition

- JWT d'accès de 15 minutes maximum, mémoire uniquement, sans refresh token.
- Claims minimaux : `sub`, `machine_id`, `session_id`, `auth_version`, `iat`,
  `exp`, `type`. Email et rôle ne font pas autorité.
- Chaque principal vérifie `type=access`, `sub == machine.owner_user_id`, User,
  Machine, état du compte, vérification, révocation et `auth_version`.
- Reset, disable, changement de rôle et « révoquer toutes les sessions »
  incrémentent `auth_version`. Désactiver un User bloque aussi ses machines
  tant que `disabled_at` est posé.
- SSE revalide au keep-alive au plus toutes les 30 secondes et ferme le flux
  en cas d'échec.
  Tout échec est fail-closed, sans retry automatique.

## Contrats et décisions

Les anciens JWT sans `auth_version` sont invalides au cutover : rupture
planifiée API/Auth rattachée à `API_CONTRACT_VERSION=2`, sous le transport
`/api/v1` conservé (aucune base `/api/v2`). Les erreurs portant un
`error_code` utilisent `{"detail":{...}}` ; les `401` génériques gardent
`{"detail":"<message>"}` (TECH/02 l.15). TECH/02, TECH/04 et TECH/05 devront être amendés. AMEND
DEC-0012, DEC-0036 et DEC-0056 ; KEEP les ADR du dépôt DEC-0011, DEC-0060 et
DEC-0098. Aucun
token, middleware, modèle, migration ou écran n'est implémenté dans DU-0.
La migration `auth_version` sera réversible et livrée avec contrats partagés,
OpenAPI, clients, fixtures et mocks des deux Blocs dans le même lot.

## Amendement A2 (proposé — serveur DEC-0121 `d03f88a5-f68a-4244-b1bb-8d9b84e2df7e`, tâche 3d774b1e)

- `GET /api/v1/auth/me` (additif) renvoie `user_id`, `display_name`, `email`,
  `role`, `machine_id` du principal ; hors contrôle projet. Il remplace la
  lecture des claims `email`/`role` côté client (`decodeJwtRole`, sur lequel
  s'appuyait DEC-0098) : AMEND DEC-0098 sur ce point.
- `TokenResponse.expires_in` (secondes, additif).
- `email_verified_at` et `disabled_at` sont introduits dès A2 ; backfill
  `email_verified_at = created_at` pour les User existants, pose immédiate
  à la création par `studio-admin`/`POST /users`.
- `studio-admin user disable|enable|revoke-sessions` ; `enable` n'incrémente
  pas `auth_version` (déjà fait par `disable`).
- Une durée JWT configurée hors 1..15 minutes empêche le démarrage.
- Contrats : TECH/02, TECH/04, TECH/05, TECH/07.
