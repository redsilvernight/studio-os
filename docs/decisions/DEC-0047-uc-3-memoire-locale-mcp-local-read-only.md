---
id: DEC-0047
title: 'UC-3 : Memory/Knowledge local-only, exposition read-only via MCP local (stdio),
  3 outils'
status: active
date: '2026-09-15'
superseded_by: null
source: docs/DECISIONS.md
sync_hash: sha256:736b28ea98cd657a61ad7d16def3792082e47ab662fe7d2ad84e87f714edbe74
---

# DEC-0047 — UC-3 : Memory/Knowledge local-only, exposition read-only via MCP local (stdio), 3 outils

Memory/Knowledge reste une capacite MAY du Universal Consumer Contract :
un consommateur fonctionne normalement sans elle. Lorsqu'elle est configuree
localement, elle est exposee en lecture seule via un serveur MCP local par
poste (transport stdio uniquement), sans endpoint HTTP VPS correspondant.
`studio_generate_context_package` reste DEFERRED avec condition de
reouverture explicite. Aucun changement a TECH/02/03/04/05, aucun endpoint,
aucun event, aucune table, aucun auth_role.

## Deux categories de capacites

### Instance capabilities

Etat partage de l'instance Studi'OS (tasks, events, worklogs, transfers,
decisions, ...). HTTP est l'interface publique canonique complete
(`TECH/02_API_CONTRACT.md`) ; le MCP du VPS est un subset additif
(DEC-0046, inchange pour cette categorie).

### Local-only capabilities

Donnees volontairement confinees au poste (vault memoire, graphe de
connaissance et leurs fichiers sources). Elles peuvent etre exposees via
une interface locale standard sans endpoint HTTP VPS correspondant.
L'absence d'un endpoint HTTP pour une capacite explicitement local-only
ne constitue pas une violation du modele Universal Consumer (amendement
additif DEC-0046, qui precise sans contredire).

## Architecture UC-3

```
AI harness compatible MCP
  → stdio
  → Studi'OS Local MCP (un processus par poste, lance par le harness)
    → handlers minces (validation I/O + enveloppe d'erreur, sans logique metier)
      → MemoryProvider / GraphProvider (abstractions, DEC-0042)
        → backend local configure (VaultMemoryProvider / GraphifyGraphProvider,
            backends optionnels parmi d'autres futurs possibles)
```

Les contrats publics parlent uniquement de Memory et Knowledge Graph.
Obsidian et Graphify ne sont pas des capacites Studi'OS : ce sont des
backends/adapters optionnels, jamais requis, jamais condition d'acces.

## Confidentialite

Les operations UC-3 (`search`, `read`, `query`) s'executent localement.
Le vault, le graphe et leurs fichiers sources ne sont ni copies ni
synchronises vers le VPS pour permettre ces operations. Le MCP du VPS ne
proxyfie aucune requete vers les postes. Aucun mecanisme de replication
de memoire privee n'est introduit par UC-3. La confidentialite filesystem
repose sur `ScopePolicy` (deny-all par defaut, DEC-0042), suffisante dans
ce contexte sans etat partage.

## Read-only

UC-3 n'introduit aucune ecriture Memory/Knowledge : `propose`,
`write_if_authorized`, `append_task_log`, `create_decision_note` restent
`write_unsupported`, `refresh_graph` reste `refresh_unsupported` et hors
surface publique UC-3. Les futures operations (`write`, `update`,
`propose`, `approval`, shared mutation) restent hors scope, renvoyees aux
etapes 8.4/8.5 sans prejuger de leur architecture.

## Transport

UC-3 local utilise stdio uniquement : pas de TCP, pas de localhost HTTP,
pas d'auth Bearer, pas de `Principal` serveur, pas de Postgres. Le
processus enfant lance par le client MCP constitue la frontiere de
confiance pour cette etape (pas d'attaquant reseau). Toute future
exposition reseau locale exige une nouvelle revue securite. Aucun code
ne depend d'un harness, provider, modele ou `agent_profile`.

## Discovery

Enregistrement conditionnel au demarrage, par processus :

- vault configure → `studio_memory_search`, `studio_memory_read` ;
- graphe configure → `studio_graph_query` ;
- backend non configure → outils absents ;
- backend configure mais temporairement indisponible → outil annonce,
  degrade machine-readable existant (`vault_missing`, `stale`, ...).

Ainsi `tools/list` decrit exactement les capacites configurees du
processus local, conformement a UC-2. Le consommateur n'a besoin de
connaitre ni Obsidian ni Graphify.

## Outils UC-3 (spec en TECH/07)

`studio_memory_search`, `studio_memory_read`, `studio_graph_query`
(read-only, bornes, scopes). Ajouts additifs : aucun outil existant
modifie. Aucune primitive de versionnement introduite ici : le
mecanisme global de versionnement des payloads MCP reste du ressort
de CC-3, qui pourra s'appliquer ensuite aux nouveaux outils comme aux
anciens.

## Context Package

`studio_generate_context_package` = DEFERRED. Reouverture uniquement par
Decision couvrant au minimum : selection des sources, confidentialite,
manifest/provenance, schema, persistance ou caractere ephemere,
frontiere local→partage, interaction avec CC-3. Roadmap : 8.3a = local
Memory/Knowledge read-only (UC-3), 8.3b = Context Package (deferred).

## Consequences

- Aucune modification runtime dans cette decision (contrats d'abord).
- Implementation a venir : entrypoint MCP local separe dans le paquet
  `studio-mcp` (handlers minces, sans import `studio_api`/DB), tests
  `tests/mcp/test_local_knowledge.py` sur fixtures `tmp_path`.
- Compatible DEC-0042 (providers/backends inchanges), DEC-0043 (aucun
  savoir harness/modele), DEC-0046 (amendement additif joint).

## Compatibilite avec les DEC existantes

Precise DEC-0046 sans la contredire (categorie ajoutee, regles
instance inchangees) ; operationalise DEC-0042 pour l'exposition ;
compatible DEC-0023 (les 3 outils sortent du lot differe, le 4eme
reste deferred avec condition) et DEC-0043/UCC (MAY, agnosticisme).
