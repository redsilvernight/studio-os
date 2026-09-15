# Studi'OS — Produit vs outillage de developpement

Frontiere normative (rectification Phase 1, DEC-0043 amendee, DEC-0044
supersedee).

## Produit Studi'OS

Ce que tout consommateur externe utilise, quel que soit son
harness/provider/model, sans `agent_profile` predefini :

- serveur : API (`TECH/02`), events (`TECH/03`), auth/sync (`TECH/04`),
  data model (`TECH/05`), stockage/transferts (`TECH/06`), MCP (`TECH/07`),
  offline sync (`TECH/08`), memoire/graphe (`TECH/09`) ;
- client de reference : `packages/studio-client` (transport generique
  HTTP/S3/MinIO, rejouable hors ligne) ;
- autorisation : `auth_role` + ownership via `authz.py` uniquement.

Le produit ne connait jamais le harness, le provider ou le modele : ce sont
des chaines ouvertes d'observabilite, jamais des discriminants metier.

## Outillage de developpement du repository

Utilise uniquement pour developper, tester, auditer et debugger ce depot :

- `studio-architect`, `studio-tester`, `contract-guardian`, `sync-debugger`
  (definitions actuelles : `.codex/agents/*.toml`, format Codex-only) ;
- dependances globales externes : `brainstormer`, `godot-tester`.

Leur harness d'execution (Codex, OpenCode, Claude Code, autre) et leur modele
relevent du profil d'execution de l'outillage, pas du protocole public
Studi'OS. Un portage vers OpenCode se fait cote outillage, sans toucher au
coeur serveur.

## Regle

Rien dans le produit ne doit exiger, enumerer ou brancher sur ces quatre
agents de developpement. Toute mention en ce sens dans la documentation est
un bug a corriger, pas une regle a suivre.
