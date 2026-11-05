# État de mission — Phase 2C

## Statut : PACKAGES_PARTIAL

Trois manifestes déterministes, avec contenus et hashes vérifiables, sont générés par `scripts/library_packages.py build` et validés par `check` et par `tests/harness/test_library_packages.py` (10 tests).

| Package | Emplacement | Entrées prêtes | Suivi Git |
|---|---|---:|---|
| Core | `library/packages/core/manifest.json` | 42 | oui (contenus : `library/studio/`, `.agents/`) |
| Project | `library/packages/project/manifest.json` | 21 | oui (contenus : `.agents/`, `library/project/`) |
| Personal | `library/packages/personal/` (manifeste + `content/`) | 21 | non, ignoré par `.gitignore` |

## Décisions (99 = 87 historiques + 12 nouvelles)

CORE_PUBLIC 42, PERSONAL_PRIVATE 21, PROJECT_SPECIFIC 21, EXCLUDED_DUPLICATE 6, NOT_READY 5, NOT_PUBLISHABLE 4. Détail et justification de chacune : `CATALOG.md`.

- Nouveaux éléments canoniques intégrés : skills `studio-task`, `studio-context`, `studio-handoff`, `studio-decision` (Core), rule `testing` et skill `graphify` (Project), skill `delegate-local` (Personal). `studio-protocol` Core est remplacée par la rule `.agents/` (v3).
- Les 6 agents créatifs de scope user sont des doublons du Core (le scope user masque studio à clé égale) : exclus, la version Core s'applique.
- Hooks utilisateur (`git-guard`, `session-start`, `stop-check`, `read-guard`, `hub-first`) : `NOT_READY`; scripts liés au câblage Claude Code et à des chemins locaux. Hooks Core : Claude Code et OpenCode seulement, Codex `unverified`, consentement requis.
- Non publiable : instructions globales, notes de vault, index/caches Hub et Graphify, credentials et sessions.

## Ce qui reste

- Les hooks Personal et la compatibilité OpenCode/Codex du Personal ne sont pas validés.
- La compatibilité réelle des runtimes n'a pas été exercée par une installation; l'import reproductible est la phase suivante.
- Les ressources historiques (`library/studio/rules/studio-protocol.md` v2) restent en place, non supprimées.
- Aucune publication, purge ni mutation de production. Rien n'est commité.
