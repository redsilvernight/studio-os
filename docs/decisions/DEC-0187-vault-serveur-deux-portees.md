---
id: DEC-0187
title: Vault serveur à deux portées (studio / projet) et DEC unifiées
status: proposed
date: '2026-10-06'
superseded_by: null
source: roadmap 63a26536 (P00-baseline)
---

# DEC-0187 — Vault serveur à deux portées (studio / projet) et DEC unifiées

Statut : **proposed** (jusqu'à accord). Équivalent serveur : DEC-0191 (`16666517-c161-4b43-b30d-1e8d48828b6f`) ; les compteurs fichier et serveur ne sont pas synchronisés (cf. DEC-0088).

Le vault devient une ressource serveur à deux portées (studio, projet). Les DEC serveur deviennent la source unique ; les fiches ADR fichiers deviennent un export Markdown.

D4 — droits de la portée studio (tranché par l'utilisateur le 2026-10-06, P03) : lecture pour tout compte actif ; création et modification en `draft`/`proposed` pour tout rôle autorisé à écrire ; `validated`, `superseded` et `archived` réservés au rôle admin. La portée projet suit les memberships (DEC-0103).

DEC-0047 (mémoire locale read-only) est à superseder après acceptation de D2.

Baseline chiffrée : `docs/DEC_BASELINE_P00.md` et `docs/DEC_RELEVANCE_BASELINE_P00.md`.
