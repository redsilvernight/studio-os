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


# État de mission — Phase 2D

## Statut : LOCAL_PARTIAL

Reconstruction, permissions, idempotence, installations et cycle de vie sont démontrés en base isolée (détail : `VALIDATION.md` § Phase 2D). Critères manquants pour `LOCAL_READY` : aucun runtime réel lancé (projections validées comme fichiers), désinstallation seulement par dépréciation et testée sur un skill, fichiers auxiliaires de 3 skills non stockés (Library = texte seul), restauration de snapshot non exercée.

| Élément | Résultat |
|---|---|
| Import Core / Project / Personal | 42 / 21 / 21 créés et activés ; rejeu = tout inchangé |
| Tests | 28 passés (18 isolés + 10 packages), 0 échec ; sans variable d'environnement les 18 sont ignorés |
| Confidentialité | l'outsider ne voit, lit, résout ni n'installe aucun item Personal |
| Hooks | Core : 3 avec consentement, Codex non supporté ; 5 hooks Personal exclus (`NOT_READY`) |
| Production | aucune mutation, aucun import réel, aucune purge |

**Reproduire** : cluster PostgreSQL local (loopback, port ≠ 5432, base `studio_lib_rebuild*`), `STUDIO_DATABASE_URL=… uv run alembic upgrade head`, puis `STUDIO_LIBRARY_REBUILD_DATABASE_URL=… uv run pytest tests/library_rebuild tests/harness/test_library_packages.py`. Import manuel : `uv run python scripts/library_import.py import --layer core|project|personal --api-url URL --token-env VAR [--project-id UUID] [--dry-run]`.

**Fichiers** : `scripts/library_import.py`, `tests/library_rebuild/`, `packages/studio-client/src/studio_client/publish.py`, docs `rebuild-2026/`. Rien n'est commité.



# État de mission — Phase 2E

## Statut : LOCAL_PARTIAL

Critères `LOCAL_READY` atteints : 3 skills multi-fichiers publiés et installés à l'identique ; 84 définitions cohérentes (42/21/21) ; installation, désinstallation et réinstallation réelles ; snapshot restauré en base isolée avec empreinte identique ; permissions et scopes préservés ; tests pertinents verts. **Critères manquants** : validation native Codex (CLI absente, blocage externe) et Claude Code (aucun diagnostic sans modèle ; appel modèle non autorisé) ; OpenCode validé avec une clé factice car le home réel masque les skills homonymes.

| Élément | Résultat |
|---|---|
| Tests | `tests/library_rebuild` + `tests/harness/test_library_packages.py` : 52 passés, 1 ignoré (symlinks) ; ciblés 285 ; contrats 592 |
| `validate-contracts.ps1` | échec du pas pytest (`infra` introuvable, script non modifié) ; ruff et mypy OK |
| Correctif | importeur : `SKILL.md` principal = le moins profond |
| Production | aucune mutation, publication, purge ni déploiement |

**Reproduire** : cluster PostgreSQL privé (`initdb`, `pg_ctl start -o "-p 54331 -h 127.0.0.1"`), `alembic upgrade head`, puis `STUDIO_LIBRARY_REBUILD_DATABASE_URL=postgresql+asyncpg://<rôle>@127.0.0.1:54331/studio_lib_rebuild STUDIO_TEST_DATABASE_URL=…/studio_client_test uv run pytest tests/library_rebuild tests/harness/test_library_packages.py -q -rs`.

**Fichiers modifiés** : `packages/studio-contracts/src/studio_contracts/library.py`, `packages/studio-client/src/studio_client/{skill_sync,projection_backups}.py`, `packages/studio-client/src/studio_client/context/library.py`, `scripts/library_import.py`, `tests/library_rebuild/test_{skill_files,snapshot_restore,package_lifecycle,native_opencode}.py`, docs `rebuild-2026/`. Rien n'est commité.
