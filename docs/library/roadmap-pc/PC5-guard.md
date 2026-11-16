# PC5 — Garde-fou contre le code mort

Le contrôle empêche le code mort supprimé en PC1 à PC4 de se reconstituer. Il tourne dans le job CI `deadcode` (`.github/workflows/ci.yml`) et échoue dès qu'un outil signale un symbole ou un fichier inutilisé qui n'est pas une exception déclarée.

## Ce que contrôle chaque outil

| Outil | Version | Périmètre | Signale | Configuration |
|---|---|---|---|---|
| vulture | 2.16 (groupe `dev` du `pyproject.toml` racine, `uv.lock`) | `services/api/src`, `services/mcp/src`, `packages/*/src` (6 répertoires), analysés ensemble pour qu'un appel entre paquets compte | fonctions, classes, méthodes, propriétés, variables, attributs et imports inutilisés, confiance ≥ 60 % | `[tool.vulture]` du `pyproject.toml` racine + `scripts/deadcode_whitelist.py` |
| knip | 6.45.1 (`npx --yes knip@6.45.1`, aucune dépendance npm ajoutée) | `dashboard/` et `desktop/` (scripts `.mjs`) | fichiers non importés, exports et types inutilisés, dépendances et binaires non déclarés | `dashboard/knip.jsonc`, `desktop/knip.jsonc` |

Les catégories structurelles de faux positifs relevées par PC0 sont écartées par les options natives des outils :

- vulture, `ignore_decorators` : routes FastAPI (`@router.*`, `@*_router.*`), validateurs et sérialiseurs Pydantic (`@field_validator`, `@model_validator`, `@model_serializer`) ;
- vulture, `ignore_names` : `dispatch` (`BaseHTTPMiddleware`), `model_config`, `settings_customise_sources`, `row_factory` (sqlite3), `__getattr__` / `__dir__` (PEP 562), arguments de `__exit__` ;
- vulture : les migrations Alembic (`services/api/alembic/versions`) et `tests/` ne sont pas dans les chemins analysés ; les outils MCP sont enregistrés par `add_tool(...)`, donc référencés ;
- knip : les plugins Vite, vitest et Playwright fournissent les entrées du dashboard ; les fichiers générés (`src/openapi-schema.ts`, `src/platform/generated/local-contracts.generated.ts`, `src/releaseNotes.generated.ts`) sont ignorés.

Le reste des exceptions est listé et justifié :

- `scripts/deadcode_whitelist.py` : 255 noms, par catégorie. Éléments PC0 « à vérifier » encore présents (56, une note par élément), contrat public PC0 (16, une note par élément), utilisés hors périmètre par `scripts/` (2), colonnes et attributs ORM (6), champs Pydantic et réglages (115), membres d'Enum (58), protocoles stdlib et annotations en chaîne (2).
- `dashboard/knip.jsonc` et `desktop/knip.jsonc` : entrées manuelles ou appelées par la CI, dépendance appelée par chemin, binaires système ; chaque ligne porte son commentaire.
- Exports « à vérifier » de PC0 dans le dashboard (21) : balise JSDoc `@public PC0 à vérifier : <raison>` sur la déclaration. `git grep -n "@public PC0"` les liste.

## Lancer en local

Depuis la racine du dépôt, après `uv sync --all-packages` et `npm ci` dans `dashboard/` :

```
uv run python -m scripts.deadcode_check            # tout (≈ 12 s)
uv run python -m scripts.deadcode_check --python   # vulture seul (≈ 4 s)
uv run python -m scripts.deadcode_check --js       # knip seul (dashboard ≈ 5 s, desktop ≈ 3 s)
```

C'est la commande exacte du job CI. Le test `tests/scripts/test_deadcode_check.py` vérifie que vulture passe sur le dépôt et échoue sur une copie où une fonction morte a été ajoutée.

## Quand la CI échoue

1. Lire la sortie : vulture donne `chemin:ligne: unused <type> '<nom>'`, knip donne la catégorie (`Unused files`, `Unused exports`...) et le fichier.
2. Cas normal : le code est vraiment mort. Le supprimer, ou retirer le mot-clé `export` s'il ne sert que dans son fichier.
3. Faux positif d'une catégorie structurelle déjà connue (nouveau décorateur de route, nouveau protocole) : étendre l'option native (`ignore_decorators`, `ignore_names`, `entry`, `ignore`) avec un commentaire.
4. Exception ponctuelle :
   - Python : ajouter `_.<nom>  # <chemin relatif>` dans la bonne catégorie de `scripts/deadcode_whitelist.py`. Hors des catégories génériques (Pydantic, Enum, ORM), écrire au-dessus une ligne `# <nom> — <raison>`.
   - TS : balise `/** @public <raison> */` sur l'export, ou entrée commentée dans `knip.jsonc` pour un fichier lancé hors import (script CI, lanceur documenté).

## Règles d'exception

- Une exception sans justification écrite est refusée en revue.
- « Utilisé seulement par les tests » ne justifie pas une exception nouvelle : c'est du code mort, sauf décision produit (citer la DEC).
- La revue de PR vérifie chaque ajout à la liste blanche, aux `knip.jsonc` et aux balises `@public`.
- Quand le code d'une exception est supprimé ou câblé, retirer l'exception dans le même commit.
- vulture compare des noms : `_.healthz` couvre tous les `healthz`. Préférer une exception sur un nom précis ; ne jamais ajouter un nom générique (`run`, `get`, `name`) à `ignore_names`.

## Mettre à jour les versions

Les deux versions sont épinglées parce qu'une nouvelle version peut changer les signalements.

- vulture : modifier `vulture==2.16` dans `[dependency-groups].dev` du `pyproject.toml`, `uv lock`, puis relancer `--python`.
- knip : modifier `KNIP` dans `scripts/deadcode_check.py` (et le schéma des `knip.jsonc` si la version majeure change), puis relancer `--js`.
- Corriger les nouveaux signalements (suppression ou exception justifiée) dans le même commit que la montée de version.

## Limites

- vulture ne voit pas les usages dynamiques (`getattr` avec un nom construit, sérialisation) : ce sont les catégories de la liste blanche. Il ne voit pas non plus les appelants hors périmètre (`scripts/`, `tests/`) : un symbole utilisé seulement par les tests passe pour mort, un symbole homonyme d'une exception passe pour vivant.
- Un nom de la liste blanche ou d'`ignore_names` masque tout nouveau symbole mort du même nom, partout.
- knip ne contrôle ni le CSS (classes inutilisées), ni le Rust de `desktop/src-tauri`, ni le sidecar Python du desktop ; il ne signale pas les exports des fichiers déclarés en `entry`.
- `scripts/`, `tests/`, `examples/`, `contracts/` et `docs/` ne sont pas contrôlés (fixtures, helpers et documents orphelins restent l'affaire des revues, comme en PC4).
