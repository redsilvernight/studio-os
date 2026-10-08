---
id: DEC-0187
title: Vault serveur à deux portées (studio / projet) et DEC unifiées
status: proposed
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0187 — Vault serveur à deux portées (studio / projet) et DEC unifiées

Statut : **proposed** (jusqu'à accord). Équivalent serveur : DEC-0191 (`16666517-c161-4b43-b30d-1e8d48828b6f`) ; les compteurs fichier et serveur ne sont pas synchronisés (cf. DEC-0088).

Le vault devient une ressource serveur à deux portées (studio, projet). Les DEC serveur deviennent la source unique ; les fiches ADR fichiers deviennent un export Markdown.

D4 — droits de la portée studio (tranché par l'utilisateur le 2026-10-06, P03) : lecture pour tout compte actif ; création et modification en `draft`/`proposed` pour tout rôle autorisé à écrire ; `validated`, `superseded` et `archived` réservés au rôle admin. La portée projet suit les memberships (DEC-0103).

D5 — recherche (P04, additif) : une note porte des ancres `task:<uuid>` / `path:<chemin>` versionnées avec elle ; `GET /vault/search` classe ancrées > liées à un saut > plein texte, exclut `superseded` par défaut et plafonne la réponse (`max_chars`). Ancres vides = `content_hash` inchangé. Contrat : `TECH/02_API_CONTRACT.md` § Vault.

D6 — contexte (P07, additif) : `prepare_context` gagne `notes` (résumés de notes vault, jamais le corps), absent sans note, tranche de 20 % de `max_chars`, statuts `validated`/`proposed` des portées projet et studio ; raisons `vault_anchor` / `vault_link`. Détail : `TECH/07_MCP_CONTRACT.md`.

D7 — import des DEC historiques (P08, serveur DEC-0192, choix utilisateur) : `studio-admin vault import-decisions` (dry run par défaut, `--apply`) crée une note `decision` par ADR fichier avec son numéro d'origine, contenu du fichier prioritaire ; une DEC serveur qui porte le même numéro qu'une décision différente est importée sans numéro (`decisions/legacy-server/…`, tag `legacy-server-dec-NNNN`) ; une DEC serveur sans fichier garde son numéro. Rejouable sans doublon ni écrasement (les dérives sont rapportées) ; la séquence est avancée au-delà du max connu. Rapport : `docs/DEC_IMPORT_P08.md`.

D8 — outils de décision (P09, serveur DEC-0193, additif) : `studio_add_decision` alloue le numéro `DEC-XXXX` côté serveur (jamais choisi à la main ; deux sessions concurrentes obtiennent deux numéros distincts) et crée une note vault `decision` de même numéro (portée projet ou studio) ; l'acceptation passe la note en `validated`, `studio_supersede_decision(decision_id, superseded_by?)` la passe en `superseded` et relie la remplaçante par un lien `supersedes`. Aucun fichier n'est créé dans `docs/decisions/` : l'export Markdown vient de P10.

DEC-0047 (mémoire locale read-only) est à superseder après acceptation de D2.

Baseline chiffrée : `docs/DEC_BASELINE_P00.md` et `docs/DEC_RELEVANCE_BASELINE_P00.md`.
