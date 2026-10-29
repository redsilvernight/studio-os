# RELEASE.md — Contrat de release Studio OS

## Cible et canal

- Cible : serveur web Studio OS sur le VPS OVH.
- Canal : `web` — déploiement continu par polling (DEC-0205).
  - Le VPS interroge `origin/deploy/ovh-vps` via `docker/systemd/studio-deploy-poll.timer`
    (`docker/deploy-poll.sh`) : sauvegarde PostgreSQL → build `api`/`mcp`/`dashboard`
    → `alembic upgrade head` → recréation des services → reload Caddy → attente `/healthz`.
  - Échec : le VPS revient seul à la révision précédente (migrations jamais annulées).

## Numérotation

- Tag de release : `vX.Y.Z` (semver) sur le commit de merge dans `master`.
- `pyproject.toml` : la version reste `0.1.0` tant qu'aucun bump n'est demandé ;
  le tag fait foi.

## Checks (une seule fois par release)

1. CI sur master, lue via `gh` après le merge `dev` → `master`
   (`gh run list --branch master --limit 5`) : `CI` doit être `completed success`.
   Aucun run = non validé ; jamais de run rows localement en substitution.
2. Les workflows desktop (`desktop-*`) et les tests Godot sont hors périmètre de ce
   canal web ; ne pas les attendre.
3. Suite de tests complète en local facultative : `pwsh scripts/test-env.ps1` puis
   `uv run pytest -n 6 -q` — seulement si la CI est douteuse.

## Flux standard

1. Partir d'un état propre (aucun modif non commitée pertinente).
2. PR `dev` → `master` (push direct interdit). CI verte via `gh`, puis merge de la PR.
3. Changelog / patch note : commits `origin/master..origin/dev` avant le merge ;
   note écrite dans `PATCH-NOTES.md` et reprise dans le message du tag et la note
   GitHub (`gh release create v<version> --notes-file`).
4. Merge de `master` dans `deploy/ovh-vps` — cette branche ne reçoit jamais autre
   chose que `master` (rule `git-clean`).
5. Confirmation explicite de l'utilisateur présentant ce qui suit, puis :
   - `git push origin deploy/ovh-vps` → le VPS déploie au prochain tick du timer.
   - `git tag -a v<version> -f` sur le commit de merge, `git push origin v<version>`.
   - `gh release create v<version> --notes-file PATCH-NOTES.md`.
6. Vérification : `curl https://<api_domain>/healthz` depuis le VPS (ou logs du
   service `studio-deploy-poll`), puis consigner la release.

## Repli

- Automatique : `deploy-poll.sh` remet la révision précédente si le build, la
  migration ou `healthz` échoue (`failed.rev` bloque la réessai automatique du même
  commit ; forcer avec `--force` côté VPS après correction).
- Manuel : revenir `deploy/ovh-vps` au commit précédent et pousser.
- Migrations jamais annulées (`alembic downgrade` interdit en prod sans décision).

## Modèle de patch note

```
# Studio OS v<X.Y.Z> — <date>

## Nouveautés
## Corrections
## Notes de mise à jour (contrats, migrations, config)
```
