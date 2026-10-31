# RELEASE.md — Contrat de release Studio OS

## Cible et canal

- Cible : serveur web Studio OS sur le VPS OVH.
- Canal : `web` — déploiement continu par polling (DEC-0205).
  - Le VPS interroge `origin/deploy/ovh-vps` via `docker/systemd/studio-deploy-poll.timer`
    (`docker/deploy-poll.sh`) : sauvegarde PostgreSQL → build `api`/`mcp`/`dashboard`
    → `alembic upgrade head` → recréation des services → reload Caddy → attente `/healthz`.
  - Échec : le VPS revient seul à la révision précédente (migrations jamais annulées).

La couche `docker/deploy-poll.sh` et `docker/systemd/` appartient à
`deploy/ovh-vps` ; elle n'est pas présente sur `dev`. Sa présence dans cette
branche ne prouve pas que le timer tourne sur le VPS. Le vérifier sur l'hôte
avant de promouvoir. La préparation de l'ouverture publique est centralisée dans
[la documentation de référence](docs/Studio_OS_Documentation_Pack/studio_os_docs/IMPLEMENTATION/05_PUBLIC_RELEASE_READINESS.md).

## Numérotation

- Les commandes `node scripts/...` ci-dessous s'exécutent depuis `desktop/`.
- Version produit canonique : `desktop/package.json` (porteuses synchronisées via
  `node scripts/version.mjs --sync` : crate Rust `src-tauri`, `DAEMON_VERSION`).
  Voir `docs/VERSION_SCOPE.md` ; `dashboard/package.json` et `pyproject.toml`
  sont volontairement indépendants.
- « Quoi de neuf » : un fichier par version dans `desktop/release-notes/0.X.0.md`
  (français simple, style des notes précédentes), puis
  `node scripts/release-notes.mjs --write` et `--check`. Le gate de release
  refuse une version sans note.
- Tag de release : `vX.Y.Z` (semver) sur le commit de merge dans `master`.
- `pyproject.toml` : versions internes de paquets, indépendantes de la version produit.

## Checks (une seule fois par release)

1. CI sur master, lue via `gh` après le merge `dev` → `master`
   (`gh run list --branch master --limit 5`) : `CI` doit être `completed success`.
   Aucun run = non validé ; jamais de run rows localement en substitution.
2. Les workflows desktop (`desktop-*`) et les tests Godot sont hors périmètre de ce
   canal web ; ne pas les attendre.
3. Avant fusion, selon les règles du dépôt : depuis la racine,
   `pwsh scripts/test-env.ps1` puis `uv run pytest -n 6 -q`, une seule fois par
   tâche. Une vérification non exécutée ou des services indisponibles ne sont
   pas une validation.

## Flux standard

1. Partir d'un état propre (aucun modif non commitée pertinente).
2. Avant la PR, préparer sur `dev` la version dans `desktop/package.json` et la
   note `desktop/release-notes/<v>.md`. Depuis `desktop/`, exécuter
   `npm run version:sync`, `npm run version:check`, `npm run notes:write`, puis
   `npm run notes:check`. Relire et versionner les changements générés.
3. PR `dev` → `master` (push direct interdit). CI verte via `gh`, puis merge de la PR.
4. Changelog / patch note : commits `origin/master..origin/dev` avant le merge ;
   note écrite dans `PATCH-NOTES.md` et reprise dans le message du tag et la note
   GitHub (`gh release create v<version> --notes-file`).
5. Merge de `master` dans `deploy/ovh-vps` — cette branche ne reçoit jamais autre
   chose que `master` (rule `git-clean`).
6. Confirmation explicite de l'utilisateur présentant ce qui suit, puis :
   - `git push origin deploy/ovh-vps` → le VPS déploie au prochain tick du timer.
   - `git tag -a v<version> -m "Studio OS v<version>" <commit-de-merge>`, puis
     `git push origin v<version>`. Un tag existant arrête la procédure : ne pas
     déplacer une version publiée.
   - `gh release create v<version> --notes-file PATCH-NOTES.md`.
7. Vérification : `curl https://<api_domain>/healthz` depuis le VPS (ou logs du
   service `studio-deploy-poll`), puis consigner la release.

## Repli

- Automatique : `deploy-poll.sh` remet la révision précédente si le build, la
  migration ou `healthz` échoue (`failed.rev` bloque la réessai automatique du même
  commit ; forcer avec `--force` côté VPS après correction).
- Manuel : préparer une révision de repli par un commit de revert relu, sans
  reset ni force-push de la branche protégée ; vérifier sa compatibilité avec
  la base déjà migrée, puis faire approuver sa promotion et son push.
- Migrations jamais annulées (`alembic downgrade` interdit en prod sans décision).

## Modèle de patch note

```
# Studio OS v<X.Y.Z> — <date>

## Nouveautés
## Corrections
## Notes de mise à jour (contrats, migrations, config)
```
