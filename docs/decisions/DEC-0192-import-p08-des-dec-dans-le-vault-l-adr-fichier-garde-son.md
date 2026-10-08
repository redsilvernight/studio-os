---
id: DEC-0192
title: 'Import P08 des DEC dans le vault : l''ADR fichier garde son numéro, la variante
  serveur en collision est importée sans numéro'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0192 — Import P08 des DEC dans le vault : l'ADR fichier garde son numéro, la variante serveur en collision est importée sans numéro

Contexte : roadmap 63a26536, étape P08. Les ADR de docs/decisions/ et la table decisions ont des numéros non synchronisés. 34 numéros désignent des décisions différentes de chaque côté (ratio de similarité des titres < 0.6), alors que vault_notes.readable_id est unique sur toute la table.
Décision (choisie par l'utilisateur) :
1. Chaque ADR fichier garde son numéro, et son contenu fait foi pour les numéros communs.
2. Une DEC serveur en collision est importée comme note decision sans readable_id, sous decisions/legacy-server/..., avec le tag legacy-server-dec-NNNN. Elle est listée au rapport et aucun numéro n'est réattribué.
3. Une DEC serveur sans fichier garde son numéro, dans la portée projet si elle a un project_id, sinon dans la portée studio.
4. Les écarts de titre et de statut sont rapportés, jamais fusionnés automatiquement (TECH/09).
5. L'import passe par studio-admin vault import-decisions : dry run par défaut, --apply pour écrire. Il est idempotent : une note existante (même numéro, ou même slug pour les notes sans numéro) n'est ni dupliquée ni écrasée, seulement signalée si elle a dérivé. Il avance decisions_readable_id_seq au-delà du numéro max connu, sans jamais la faire reculer.
