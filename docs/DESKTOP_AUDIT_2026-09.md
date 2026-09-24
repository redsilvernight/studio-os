# Audit Desktop et daemon embarqué — septembre 2026

Branche `fix/desktop-audit-2026-09`, fusionnée dans `master` puis `deploy/flo-laptop`.
Le rapport complet (reproductions, résultats de tests) est le PDF local
`AUDIT_DESKTOP_2026-09.pdf` (non versionné). Cette note garde l'état utile à la reprise.

## Corrigé

| Anomalie | Commit |
| --- | --- |
| CI lint : 9 fichiers non formatés (`ruff format`) | `666f8ba` |
| CI mypy : verrou d'instance du daemon non gardé par plateforme ; `DEFAULT_MAX_CHARS` non réexporté | `a8cb30a` |
| CI pytest : 10 tests `tests/harness` dépendants des harnais installés sur la machine | `0e53126` |
| CI dashboard e2e : `ui4.spec.ts` antérieur à DEC-0098 (Accepter/Remplacer) | `6b07de0` |
| Wizard : la reprise après redémarrage effaçait l'association du dossier si le daemon n'était pas prêt | `9797080` |
| Wizard : création de projet toujours en échec (slug manquant, 422, message trompeur) ; liste des projets sans relance ; doubles clics (projets en double, associations/applications multiples) ; rejets harnais silencieux | `d835c2f` |
| Desktop : la CSP bloquait les uploads directs vers le stockage pré-signé (option de build `--storage-url`) | `19b38ca` |
| Desktop validation : ne tournait que sur PR/dispatch ; échecs illisibles sans compte GitHub | `a8d59b5`, `f853907`, `5511c67`, `d677eee` (annotations) |
| Desktop validation : `test:install` ne pouvait pas s'attacher en CDP (WebView2 152 ignore `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` sous wry) | `d677eee` |

## Documenté, non corrigé

- **S3 HTTP depuis une page HTTPS** : `STUDIO_S3_PUBLIC_ENDPOINT_URL=http://100.124.49.80:9000`.
  Les uploads directs du Dashboard web servi en `https://flo-laptop.tailf61f85.ts.net` sont
  bloqués (contenu mixte). Le Desktop ne peut pas l'autoriser non plus : `--storage-url`
  refuse une origine HTTP distante sans l'opt-in explicite. Piste : exposer MinIO en HTTPS
  (bloc `{$STORAGE_DOMAIN}` du Caddyfile ou un port Tailscale Serve dédié), vérifier que la
  signature SigV4 survit au proxy (en-tête `Host`), puis builder le Desktop avec `--storage-url`.
- **Installateur non signé** : SmartScreen avertit ; Smart App Control (actif sur FLO-LAPTOP)
  bloque les binaires non signés. Il bloque aussi `rustc` (proc-macros locales) : ni build Rust
  ni `test:install` ne sont possibles sur ce poste. Tout passe par la CI Windows.
- **Wizard** : l'étape « Dossier » propose « Passer » alors que « Terminer » exige un dossier.
- **Sidecar** : un échec de lancement rend le daemon indisponible pour toute la session
  (pas de nouvelle tentative) ; l'état « abandonné » reste affiché après une reprise.
- **Port de débogage WebView2 en release** (réserve studio-tester) : `webview_args.rs` transmet
  `--remote-debugging-port` dès que `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` le demande, comme
  le faisait WebView2 nativement. Tout processus local peut alors piloter la webview (et son
  jeton) tant que la variable est posée. Le restreindre à un build de test empêcherait de
  valider l'installateur réel ; à reconsidérer avec la signature. `WRY_DEFAULT_ARGS` est une
  copie des défauts de wry 0.55.1 : à revérifier à chaque montée de wry.
- **`onboarding-walkthrough.mjs`** exige une sélection humaine dans le sélecteur natif : non exécuté.
- **pytest instable** : un échec isolé sur le run 35936871212 (`5511c67`), non reproduit ensuite ;
  les annotations pytest ajoutées nommeront le test à la prochaine occurrence.

## Reprise

- Installateur de la version corrigée : pré-release `desktop-flo-laptop-*` publiée par
  `.github/workflows/desktop-installer-flo-laptop.yml` (branche `deploy/flo-laptop` uniquement).
- Suite suggérée : HTTPS pour le stockage, puis rebuild du Desktop avec `--storage-url` ;
  décider de la signature de code (certificat) avant toute distribution hors du poste.
