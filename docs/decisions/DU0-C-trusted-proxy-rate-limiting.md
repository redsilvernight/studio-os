---
title: "DU-0/C — Proxy de confiance et anti-abus par étages"
status: proposed
server_decision_id: df4d6d3b-5682-4ee1-8460-410ebaf4c102
server_readable_id: DEC-0106
server_replaces: a4b001d3-217c-4e80-b72a-ed2f869f3259 (DEC-0100 serveur, superseded ; collisionnait avec l'ADR du dépôt DEC-0100)
---

# DU-0/C — Proxy de confiance et anti-abus par étages

## Current

Le limiteur est en mémoire par processus. Il utilise le hash de n'importe quel
Bearer, sinon le premier `X-Forwarded-For`, sinon le peer. Aucun proxy de
confiance n'est configuré : faux Bearer et XFF sont donc rotatifs/usurpables.

## Options

1. Faire confiance à tout XFF : rejeté.
2. Ignorer les headers proxy : incompatible avec Caddy.
3. Vérifier le saut immédiat et composer plusieurs limites : recommandé.

## Proposition

- Caddy écrase les headers entrants. L'API ne lit Forwarded/XFF que si le peer
  immédiat appartient à une liste CIDR explicite ; sinon elle les ignore.
- Pré-auth : bucket par IP canonique et endpoint. Post-auth : bucket
  supplémentaire par identité validée, jamais par Bearer arbitraire.
- Login/register/verify/resend/forgot/reset ont des limites strictes, réponses
  non énumérantes et travail factice contre les écarts temporels.
- Toutes les limites doivent passer ; `429` et `Retry-After` sont stables et
  bornés. Le cache mémoire est borné.
- Le store mémoire n'est permis qu'en mono-réplique. Un store atomique partagé
  est requis avant toute réplication de l'API.

## Contrats et décisions

Les nouveaux `429` et leur `Retry-After` sont une rupture API/Auth rattachée au
contrat 2, pas une simple documentation. TECH/02 et tous les clients/mocks A/B
définiront l'enveloppe `detail`; TECH/04 et l'exploitation documenteront la
chaîne de confiance. L'enveloppe Event ne change pas. AMEND l'ADR du dépôt
DEC-0060 ; KEEP les ADR du dépôt DEC-0011, DEC-0012, DEC-0056 et DEC-0098.
Aucun runtime n'est modifié dans DU-0.
