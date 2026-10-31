---
id: DEC-0250
title: 'Frontière identité : alias exacts documentés et exception AST bornée aux gardes
  de neutralité'
status: accepted
date: '2026-10-29'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0250 — Frontière identité : alias exacts documentés et exception AST bornée aux gardes de neutralité

Proposition issue de l’acceptation intégrée et revues contract-guardian/studio-architect du 29/10/2026. TECH/02 impose les seuls alias codex[-cli|-desktop], claude[-code|-cli|-desktop], opencode[-cli|-desktop]. La suppression générique des suffixes fusionnait indûment custom-cli/custom, codex-code/codex et des suffixes empilés. Garder logical_harness à la frontière partagée studio_contracts.agent_identity ; table déclarative exacte de sept paires, fallback trim/minuscule/_→- sans fusion. Les gardes historiques du cœur autorisent par AST uniquement cette affectation dans ce seul module, après vérification égalité complète des sept paires ; ils continuent de scanner tout le code restant, branches/catalogues/littéraux inchangés. Pas d’exclusion globale de module ni déplacement client qui ferait varier l’identité selon entrée. Correction de dérive vis-à-vis du contrat existant, sans changement de forme HTTP. Anciennes fiches et historique conservés ; aucun rapprochement/migration automatique : l’identifiant brut ancien ayant été perdu, un harnais personnalisé précédemment fusionné pourra obtenir un nouvel UUID à sa prochaine résolution. Cette proposition ne vaut ni approbation ni déploiement.
