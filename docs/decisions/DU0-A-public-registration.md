---
title: "DU-0/A — Inscription publique fermée par défaut"
status: proposed
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
