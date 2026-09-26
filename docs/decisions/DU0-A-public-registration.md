---
title: "DU-0/A — Inscription publique fermée par défaut"
status: active
server_decision_id: bcf92622-8b2a-48fa-bb16-bf345b867489
server_readable_id: DEC-0109
server_replaces: 61b0a658-657d-41bc-9114-23c509d4464a (DEC-0104, superseded) ; a4c86edd-a071-40dd-9e76-92af9245c0c8 (DEC-0098 serveur, superseded)
---

# DU-0/A — Inscription publique fermée par défaut

## Current

Il n'existe pas d'inscription publique. `POST /users` et `POST /machines` sont
admin-only ; le premier admin reste provisionné hors-bande selon DEC-0011. Le
modèle User ne possède pas encore d'état actif ou vérifié.

## Options

1. Inscription toujours ouverte : rejetée, car elle augmente sans borne la
   surface d'abus et change le modèle d'exploitation.
2. Invitation uniquement : sûre, mais ne couvre pas l'objectif public.
3. Flag d'instance, désactivé par défaut : recommandé.

## Proposition

- `PUBLIC_REGISTRATION_ENABLED=false` par défaut. Désactivé, le futur
  `POST /api/v1/auth/register` répond `404 registration_unavailable`.
- Activé, il crée un User `readonly`, état `pending`, `email_verified_at` nul,
  sans membership.
  Le rôle dit quoi faire ; la membership dit où.
- Les réponses register/resend/forgot sont non discriminantes. Les emails sont
  normalisés et uniques.
- Vérification et reset utilisent des secrets aléatoires d'au moins 256 bits,
  hashés, typés, expirants, consommés une seule fois dans une transaction.
- `register`, `resend` et `forgot` exigent `Idempotency-Key` et rejouent la
  réponse d'origine sans créer de User ou secret supplémentaire. `verify` et
  `reset` sont consommables une fois ; un rejeu identique retourne le résultat
  terminal d'origine, un payload différent est refusé
  (`409 idempotency_key_payload_mismatch`). La réponse stockée pour le rejeu
  ne contient aucun secret.
- L'activation exige `email_verified_at`. Tant que `disabled_at` est posé
  (état `disabled`), JWT, machines, SSE et MCP dérivés du User sont bloqués.
- Les erreurs portant un `error_code` utilisent l'enveloppe TECH/02
  `{"detail":{"error_code":...}}` ; les `401` génériques gardent
  `{"detail":"<message>"}` (TECH/02 l.15).
- Le bootstrap hors-bande DEC-0011 reste inchangé. L'enrôlement machine
  self-service appartient à A5, après session humaine vérifiée.

## Contrats et décisions

Nouvelles routes du contrat API 2 et modèle de jeton : additifs. L'application obligatoire de l'état
de compte est une rupture rattachée à `API_CONTRACT_VERSION=2` (transport
`/api/v1` conservé, aucune base `/api/v2`). TECH/02, TECH/04 et TECH/05 devront être
mis à jour avec les deux Blocs et leurs mocks. AMEND DEC-0012 et DEC-0056 ;
KEEP les ADR du dépôt DEC-0011, DEC-0036 et DEC-0098. Aucun code n'est
implémenté dans DU-0.
Les migrations futures doivent être réversibles et tester l'ordre de rollback
applicatif ; contrats, OpenAPI, clients, fixtures et mocks A/B changent dans le
même lot.

## Amendement A3 (accepté — serveur DEC-0122 `668fc649-0c1f-43b4-b3fb-12dcbb4e3535`, tâches f1c0664c / 4cb7a6bd)

- Administration HTTP des comptes, rôle `admin` : `POST /api/v1/users/{id}/disable|enable|revoke-sessions`
  et `GET /api/v1/users/{id}/memberships` (additifs), en plus de la CLI
  `studio-admin user …` prévue par DEC-0110.
- Aucun endpoint ne permet à un User de modifier son propre rôle, état ou accès :
  cibler soi-même répond `403 self_modification_forbidden` avant toute recherche,
  y compris `PUT`/`DELETE /projects/{id}/members/{user_id}` (rupture rattachée à
  `API_CONTRACT_VERSION=2`). Aucun endpoint ne modifie `User.role`.
- `User` expose `status` dérivé (`pending|active|disabled`), `email_verified_at`,
  `disabled_at` (additif).
- E-mails normalisés `strip().lower()`, uniques sans casse (index sur
  `lower(email)`). La migration `0016` réécrit les e-mails existants en
  minuscules : transformation **irréversible** (le downgrade restaure la
  contrainte, pas la casse d'origine) ; préflight bloquant sur les doublons.
  Son exécution sur une instance réelle exige un accord explicite, donné par\n  l'utilisateur le 2026-09-26 avec l'acceptation de DEC-0122.
- Contrats : TECH/02, TECH/04, TECH/05.

## Amendement A4 (accepté — serveur DEC-0128 `65ddfa48-bf06-497f-a97b-03712e5eb6a7`, tâches 7e9b8172 / bf9c4d6e / 7898c5ec / 4f5c0616)

- `register` ne reçoit que l'adresse ; mot de passe et `display_name` sont
  choisis à `verify-email` par le détenteur de la boîte. Motif : revue
  contract-guardian — lier le mot de passe à l'inscription permettait une
  pré-prise de compte (un tiers inscrit l'adresse, la victime active le compte
  avec le mot de passe du tiers) et laissait un tiers écrire du texte dans
  l'e-mail envoyé. Un compte non `pending` ne peut plus être « re-vérifié ».
- La récupération (`forgot-password`/`reset-password`) ne dépend pas du flag
  d'inscription : elle est disponible dès qu'un backend e-mail est configuré
  (`STUDIO_EMAIL_BACKEND` ≠ `disabled`), sinon `404 password_recovery_unavailable`.
  Un reset réussi rend `active` un compte `pending` (la boîte est prouvée).
- `POST /auth/change-password` (additif, principal authentifié, mot de passe
  courant exigé) ; reset et changement révoquent toutes les sessions via
  `auth_version` (A2).
- Fournisseur e-mail : `disabled` | `file` (dev) | `smtp`, secrets en
  environnement uniquement ; l'API refuse de démarrer sur une configuration
  incohérente (inscription sans backend, `file` en production, base URL non
  HTTPS avec inscription ouverte).
- Limites connues, acceptées : écart de temps de réponse (écritures DB) entre
  adresse connue et inconnue sur `register`/`forgot` — le corps est identique
  et l'e-mail part après la réponse ; un crash entre le commit métier et la
  complétion de la clé d'idempotence peut, après reprise (30 s), envoyer un
  second e-mail.
