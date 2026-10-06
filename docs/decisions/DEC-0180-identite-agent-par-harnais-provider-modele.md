---
id: DEC-0180
title: 'AIB L2 : identite agent par (harnais, provider, modele) sur tous les harnais'
status: accepted
date: '2026-10-03'
superseded_by: null
source: docs/AI_BOOTSTRAP_ROADMAP.md
---

# DEC-0180 — identite agent par (harnais, provider, modele)

Statut `accepted` (demande et validation humaines du 2026-10-03, proprietaire
du depot). Complete DEC-0099 (le hook assure l'agent du harnais) et l'ajout
`stable_key` / `POST /agents/ensure` (migration `0019`).

## Contexte

Depuis l'ajout de `POST /agents/ensure`, l'identite d'un agent est un couple
(machine, `stable_key`) unique. Or le bloc modele qui derive cette cle d'un
couple (harnais, modele) n'etait actif que pour OpenCode, et uniquement sur la
sortie texte. Les harnais a sortie JSON (Claude Code) et les harnais sans bloc
modele (Codex) ne resolvaient qu'un agent par harnais, en plus des agents par
modele pour les autres — d'ou des identites multiples pour un meme modele, et
un agent per-harnais cree systematiquement meme lorsque le modele etait connu.

## Decide

- L'identite d'un agent de harnais est le couple **(harnais, provider, modele)**
  des que le harnais expose son modele dans l'entree du hook (`payload.model`).
  La `stable_key` correspondante est `agents-ensure-<harnais>:<provider>/<modele>`,
  resolue via `POST /agents/ensure` (idempotent, deja au contrat).
- Le bloc modele est **commun a toutes les sorties** (texte et JSON) et a
  **tous les harnais** ; le template ne depend plus d'un drapeau par harnais.
- Quand un agent de modele est resolu, **l'agent per-harnais n'est pas cree**
  (plus de doublon) ; il reste le **repli** lorsque le harnais n'expose pas de
  modele. Le cache local `studio-agent.json` reste scope par origine serveur et
  porte la cle modele `<harnais>:<origine>:<provider>/<modele>`.
- Aucun changement de contrat (API, Event, Auth/Sync, Data Model, MCP) :
  `stable_key` et `POST /agents/ensure` etaient deja additifs. Changement
  strictement client (`packages/studio-client`).

## Consequences

- Un changement de modele cree une nouvelle identite stable et dedupliquee,
  au lieu d'un `409 idempotency_key_payload_mismatch` ou d'un agent per-harnais
  divergdant. La granularite reste choisie par l'appelant via `stable_key`.
- Les agents per-harnais existants (cles `agents-ensure-<harnais>` sans modele)
  ne sont plus recrees par les hooks qui exposent un modele ; ceux deja en base
  restent intacts tant qu'aucune migration de donnees n'est demandee.
- Fail-open inchange : tout echec (hors ligne, sans credential) laisse le hook
  silencieux, code 0, sans secret ecrit ; le modele n'est jamais une entree
  d'autorisation.
- Ecarte : rendre les metadonnees mutables pour une meme `stable_key` (upsert) —
  cela rouvrirait l'ambiguite d'attribution que `ensure` ferme par un `409`.
