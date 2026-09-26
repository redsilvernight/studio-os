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
| Wizard (revue studio-tester) : noms sans slug exploitable refusés ; clé d'idempotence réutilisée pour une relance | `86aba61` |
| pytest instable : `test_server_origin_switch` rejouait l'outbox avant l'échéance du backoff | `d3caed1` |
| Desktop validation : `test:install` ne pouvait pas s'attacher en CDP (WebView2 152 ignore `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` sous wry) | `d677eee` |
| `test:install` : fermeture demandée via `pwsh`, absent d'un Windows standard (échec local 28/29) | `71fbb3a` |

## Suivi du 2026-09-24 (branche `fix/desktop-audit-followups`)

| Point | Traitement |
| --- | --- |
| A15 — « Passer » sur l'étape Dossier obligatoire | Bouton retiré : l'étape est `required` et « Terminer » exige un dossier |
| A16 — Sidecar sans nouvelle tentative | Échec de lancement retenté après 15 s (binaire absent ou protocole incompatible : jamais) ; un lancement réussi efface « indisponible » et « abandonné » |
| A17 — Port de débogage WebView2 en release | Refusé quand `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` est une variable persistante (utilisateur ou machine) ; une valeur posée pour le lancement (scripts de test) reste acceptée |
| Actions GitHub Node 20 | `checkout@v5`, `setup-node@v5`, `upload-artifact@v6`, `setup-uv@v7` (Node 24) |
| A13 — S3 en HTTP depuis une page HTTPS | Tailscale Serve `https://flo-laptop.tailf61f85.ts.net:8443` (tailnet only) → Caddy `:9000` → MinIO ; `STUDIO_S3_PUBLIC_ENDPOINT_URL` du `.env` live pointé dessus. Vérifié : PUT/GET pré-signés (SigV4 intact), CORS pour l'origine du Dashboard. Installateur flo-laptop construit avec `--storage-url` (`deploy/flo-laptop` 247b641) |

Reste ouvert : A14 (Smart App Control / signature de code : certificat requis, paramètre
de sécurité du poste non modifiable par un agent).

## Documenté, non corrigé (état initial de l'audit)

- **S3 HTTP depuis une page HTTPS** : `STUDIO_S3_PUBLIC_ENDPOINT_URL=http://100.124.49.80:9000`.
  Les uploads directs du Dashboard web servi en `https://flo-laptop.tailf61f85.ts.net` sont
  bloqués (contenu mixte). Le Desktop ne peut pas l'autoriser non plus : `--storage-url`
  refuse une origine HTTP distante sans l'opt-in explicite. Piste : exposer MinIO en HTTPS
  (bloc `{$STORAGE_DOMAIN}` du Caddyfile ou un port Tailscale Serve dédié), vérifier que la
  signature SigV4 survit au proxy (en-tête `Host`), puis builder le Desktop avec `--storage-url`.
- **Installateur non signé** : SmartScreen avertit ; Smart App Control (actif sur FLO-LAPTOP)
  peut bloquer les binaires non signés. Il bloque `rustc` (proc-macros compilées localement)
  sur ce poste : tout build Rust passe par la CI Windows. L'installateur CI s'installe et se
  lance localement, mais SAC a bloqué `studio-daemon.exe` (sidecar PyInstaller non signé) lors
  d'un second lancement : sur FLO-LAPTOP, le daemon du Desktop peut être indisponible tant que
  les binaires ne sont pas signés.
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

## Reprise

- Installateur de la version corrigée : produit et publié par
  `.github/workflows/desktop-channels.yml` (canal `prod`, branche `deploy/flo-laptop`).
  Le workflow `desktop-installer-flo-laptop.yml` (deploy-only) a été supprimé —
  B5/T3, DEC-0098 : aucune feature uniquement sur `deploy/*`.
- Suite suggérée : HTTPS pour le stockage, puis rebuild du Desktop avec `--storage-url` ;
  décider de la signature de code (certificat) avant toute distribution hors du poste.
