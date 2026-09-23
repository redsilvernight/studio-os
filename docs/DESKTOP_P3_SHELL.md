# Desktop P3 — Shell & UX Desktop

Base : `desktop/integration` @ `12efe5a` (P2). Branche : `desktop/shell`. Le Dashboard web reste indépendant : tout ce qui suit est inerte hors Desktop.

## 1. Périmètre

P3 ajoute l'UX du shell autour du socle P2 : états de connexion, `server_origin` configurable à l'exécution, sélecteurs natifs, page Réglages › Application, état du daemon (affichage seul). Hors périmètre (P4/P5) : cycle de vie du daemon, collecte/rotation/export de journaux, Workspace Manager, association dossier ↔ projet.

## 2. Commandes shell natives (hors protocole P1)

Ce ne sont **pas** des extensions `studio.local/v1` : elles ne passent pas par `bridge_request`, ne figurent pas dans l'allowlist P1 et ne touchent pas `contracts/`. Elles sont typées, une par usage, sans primitive générique (pas de `read_file(path)`, pas de proxy HTTP).

| Commande | Rôle | Garde-fous |
|---|---|---|
| `get_server_origin` | `{configured, applied, restart_required}` | appelant de confiance ; `applied` = origine autorisée par la CSP de ce processus (`null` = défaut du build) |
| `set_server_origin` | enregistre/efface l'origine (stockage local non secret `shell-settings.json`) | validation Rust stricte (codes stables), aucune application à chaud |
| `restart_desktop` | relance explicite (arrêt propre du sidecar d'abord) | jamais déclenché sans action utilisateur |
| `choose_folder` / `choose_file` | dialogue natif (crate `rfd`, pas de plugin Tauri) | le renderer ne reçoit que le choix ; annulation = issue normale ; aucun scan implicite ; consommé par P5 |

Permissions générées par `build.rs` (`command_names::APP_COMMANDS` → `capabilities/main-window.json`). Aucun plugin (`tauri-plugin-shell/fs/http/opener` interdits par test Cargo).

## 3. `server_origin` à l'exécution

- Validation (Rust, source de vérité) : https requis ; http seulement `localhost`/`127.0.0.1` ; ni identifiants, chemin, requête ni fragment ; l'origine Desktop `http://tauri.localhost` est refusée (elle sert au CORS serveur, jamais d'URL serveur). Le renderer traduit les codes en messages français.
- **CSP statique par build** : l'origine enregistrée est injectée par Rust dans `connect-src` (et nulle part ailleurs) avant la création de la webview. Un changement n'est donc effectif qu'après relance explicite ; d'ici là le renderer continue d'utiliser `applied`. Vérifié sur l'exe réel : la nouvelle origine est bloquée avant relance, autorisée après ; une origine arbitraire reste bloquée.
- Sans adresse effective (build sans `--api-url` et rien d'enregistré) : `observedFetch` refuse toute requête (décision sur l'adresse effective, pas sur l'URL : openapi-fetch fournit une `Request` déjà résolue contre `tauri.localhost`) ; état « Serveur injoignable » et message « Aucune adresse configurée ». Login, SSE, machines, overview et sonde `/healthz` passent tous par ce garde.

## 4. États et priorité

`protocole incompatible > serveur injoignable > session expirée > assistant local indisponible > redémarrage requis > connecté > connexion…`. Statut simple dans la barre haute (pastille), détails progressifs dans Réglages › Application. Reprise sans redémarrage : backoff de sonde `/healthz`, tout appel API abouti rétablit l'état, un 401 renvoie vers la connexion avec un message explicite.

L'état du daemon vient de `daemon.status` (P1, `DaemonRunState` + codes d'erreur P1) ; aucun état n'est inventé. `not_supported` (daemon non livré) n'est pas une alerte ; `daemon_unavailable`/`daemon_crashed` le sont.

## 5. Web vs Desktop

`platform/` expose des adaptateurs `web`/`desktop` ; seul `platform/desktop.ts` touche `__TAURI__` (test de confinement). En web : pas d'observateur, pas d'override, pas de pastille, Réglages › Application n'affiche que l'identité et la note « Application Desktop non utilisée » (aucun contrôle natif).

## 6. Tests

- Vitest : 787 tests au moment de P3 (835 sur la baseline Wave 1 ; dont ~95 P3 : origine runtime, observateur d'API, machine d'états, résumés, Desktop shell, Réglages › Application, connexion, absence d'API natives).
- Rust : `cargo test` 47 tests (validation d'origine, CSP, sélecteurs, ACL/commandes).
- Playwright web : 172 tests, sans régression.
- E2E Desktop réel (WebView2, sans Postgres) : `node desktop/scripts/build.mjs --api-url http://127.0.0.1:59999` puis `npm --prefix desktop run test:e2e:shell` — 25 contrôles (origine valide/invalides, CSP avant/après relance, relance explicite, pastille, Réglages, reprise serveur).
- `desktop/scripts/make-config.mjs --check` : CSP synchronisée.

## 7. Dette et limites

- Les dialogues natifs (`choose_folder`/`choose_file`) ne sont pas automatisables en E2E ; couverts par tests unitaires Rust/TS et par le refus ACL/typage.
- P1 n'expose aucune commande de diagnostic/journaux : l'entrée « Ouvrir les journaux » est visible mais désactivée (« Non disponible dans cette version ») — P4.
- `local-contracts.generated.ts` : la dérive CRLF observée sous Windows est résolue en Wave 1 (`.gitattributes` + comparaison canonique LF), voir `DESKTOP_WAVE1_INTEGRATION.md`.
- E2E `scripts/e2e.mjs` (P2, avec Postgres + sidecar) non rejoué dans ce lot.
