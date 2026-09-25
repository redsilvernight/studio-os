---
id: DEC-0096
title: 'Desktop P9 : adaptateurs de harnais au scope projet, jeton par référence, fail-closed'
status: proposed
date: '2026-09-22'
superseded_by: null
source: docs/decisions/DEC-0096-desktop-p9-harness-adapters.md
---

# DEC-0096 — Desktop P9: harness adapters

Status: **proposed**
Date: 2026-09-22
Task: `[Desktop P9] Harness Adapters (Claude Code, OpenCode)`

Note de réconciliation (2026-09-22, intégration P9+P10) : cette décision a été
créée sous l'identifiant DEC-0095 sur la branche `desktop/harness-adapters`,
en collision avec DEC-0095 déjà attribué à la décision P10 (packaging Windows
NSIS, Graphify non redistribué) — celle-ci existait déjà côté serveur Studio OS
avec le statut `proposed` (task_id `b0cb4b94-8ed6-4f67-bc6b-c2c9063831f9`).
DEC-0095 est conservé pour la décision P10 afin de rester cohérent avec l'état
serveur déjà en place ; cette décision P9 est renumérotée DEC-0096, seul
identifiant libre suivant, et son statut ramené à `proposed` (elle n'avait
jamais été soumise/acceptée côté serveur malgré le `active` déclaré sur la
branche source). Contenu de la décision inchangé sur le fond.

## Context

Desktop doit détecter et configurer les harnais IA installés (Claude Code,
OpenCode) pour qu'ils utilisent le MCP Studi'OS, sans logique éditeur hors d'un
adaptateur et sans toucher à ce que Studi'OS ne gère pas.

## Decision

- Architecture `HarnessRegistry` → `HarnessAdapter` ; ajouter un harnais = un
  adaptateur enregistré, sans changement du domaine serveur ni du contrat P1
  (`harness.*` réutilisé tel quel).
- Scope **projet uniquement**, à la racine d'un dossier de travail connu :
  `.mcp.json` (Claude Code), `opencode.json[c]` (OpenCode). Les configurations
  utilisateur/globales, qui portent comptes et fournisseurs, ne sont jamais
  touchées.
- Studi'OS ne gère ni modèle, ni abonnement, ni clé de fournisseur : aucun code
  P9 ne nomme, lit, demande ni ne stocke de tel identifiant. Le jeton Studi'OS
  n'est jamais copié : seule une référence à `STUDIO_MCP_MACHINE_TOKEN` est
  écrite. **Amendé par DEC-0104 §2** : scope utilisateur de l'outil et
  identifiant dédié par couple poste + outil, au lieu du scope projet et de la
  référence.
- Fail-closed : version inconnue ou trop récente (Claude Code ≠ majeure 2,
  OpenCode ≠ majeure 1), fichier invalide ou sans édition sûre → aucune écriture.
- Écriture : aperçu sans effet → sauvegarde locale bornée (10 par dossier et
  adaptateur, jamais envoyée au serveur) → validation → fichier temporaire →
  remplacement atomique → vérification. Rollback refusé si le fichier a divergé
  du hash post-application.
- Le Dashboard n'accède jamais aux fichiers ni aux exécutables : il passe par le
  pont `harness.*`. Le Web indique seulement que la fonction appartient à
  Studi'OS Desktop.

## Consequences

Windows d'abord, aucune validation Linux/macOS revendiquée. Le pont ne servant
pas `workspace.*`, l'écran prend l'identifiant du dossier dans la route.
Détails : `docs/DESKTOP_P9_HARNESS_ADAPTERS.md`.
