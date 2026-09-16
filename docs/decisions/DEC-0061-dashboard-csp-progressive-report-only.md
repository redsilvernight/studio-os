---
id: DEC-0061
title: 'Dashboard CSP progressive : tests statiques, e2e Playwright, Report-Only'
status: active
date: '2026-09-16'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0061 — Dashboard CSP progressive : tests statiques, e2e Playwright, Report-Only

Lève le point différé de DEC-0060 (« pas de CSP : non vérifiable sans build
navigateur ») par une mise en place progressive et testable. Aucun
enforcement bloquant dans ce lot : uniquement `Content-Security-Policy-Report-Only`.
Aucun changement de contrat (`TECH/02-05/07` intacts), aucune migration.

## Décision

1. **Tests statiques (vitest, `dashboard/src/csp-static.test.ts`, 5 tests).**
   Pré-requis d'une CSP stricte figés : `dist/index.html` sans script inline,
   sans bloc `<style>`, sans handler inline ni `javascript:` ; templates
   `src/**/*.ts` sans attribut `style=` ni `on*=` dans un tag. Échec explicite
   si `dist/` n'est pas construit (`npm run build` d'abord, comme en CI).

2. **Politique unique et templatée (`dashboard/csp-policy.ts`).**
   `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
   font-src 'self'; connect-src 'self' <EXTRA>; object-src 'none'; base-uri 'self';
   form-action 'self'; frame-ancestors 'self'`. Pas de `navigate-to`, pas de
   `worker-src`/`media-src` (aucun worker ni média dans la SPA ; `default-src`
   couvre un ajout futur, à réévaluer alors). Paramètres d'environnement
   (jamais d'origine en dur) : `connectExtra` = domaine storage des URLs
   pré-signées (uploads directs, DEC-0025) + origine API seulement quand
   `VITE_STUDIO_API_URL` pointe cross-origin au build.

3. **Vrai test navigateur (`dashboard/e2e/csp.spec.ts`, Playwright).**
   `vite preview` sert `dist/` avec le header Report-Only
   (`vite.config.ts:preview.headers`) ; l'API est stubbée par
   `page.route` (zéro backend dans ce job) : login `POST /auth/token` →
   shell → `#/`, `#/projects`, `#/tasks`, `#/machines` (stub 404, chemin
   Derived DASH-4), `#/decisions`, `#/transfers` (stubs `{items: []}` et
   consommation nulle). Échec sur toute erreur console CSP, toute
   `pageerror`, ou header Report-Only absent. Job CI `dashboard` :
   `npm ci` → build → vitest → `playwright install --with-deps chromium` →
   `npm run test:e2e`.

4. **Report-Only côté déploiement.** `docker/Caddyfile` (site dashboard) émet
   la même politique en Report-Only, `connect-src` templaté par
   `https://{$STORAGE_DOMAIN}` + `{$DASHBOARD_CSP_CONNECT_EXTRA}` (vide par
   défaut = prod same-origin ; `docker/.env.example` documente le paramètre,
   `docker-compose.yml` le propage au conteneur Caddy). Pas de `report-uri` :
   aucun collecteur dans ce lot, les navigateurs journalisent en console.

5. **Pas d'enforcement dans ce lot.** Conditions de sortie Report-Only →
   enforcement (changement documenté ultérieur, pas automatique) : e2e vert
   sur les parcours principaux **avec un backend réel ou des stubs couvrant
   les écritures** (upload transfert, login JWT réel), zéro violation
   observée en staging sur au moins un cycle d'usage réel, puis bascule du
   header `Content-Security-Policy-Report-Only` vers
   `Content-Security-Policy` dans `Caddyfile` + `vite.config.ts`.

## Preuves

- `cd dashboard && npm run build` → `tsc --noEmit` + vite verts.
- `npm test` → 100 passed (95 existants + 5 `csp-static`).
- `npm run test:e2e` → 1 passed (login + 6 routes, 0 violation CSP, 0 pageerror).
- `caddy validate` vert (variantes `DASHBOARD_CSP_CONNECT_EXTRA` vide et renseigné) ; `docker compose config` interpole la variable.
- CI : job `dashboard` vert (build, vitest, chromium, e2e).

## 9.1c dispatch — statut inchangé (documentation seule)

Conformément à DEC-0059 (§110-111, §225-227) et à l'absence de besoin concret
exprimé : aucun endpoint `POST /builds`, aucun appel sortant authentifié en
écriture, aucun token `actions:write`. Ce lot ne touche pas à 9.1c en dehors
de cette réaffirmation. Prérequis d'une éventuelle activation future : besoin
réel tranché, `POST /builds` (`admin|developer`, `Idempotency-Key`), garde
d'idempotence en DB avant l'appel sortant, tests sur HTTP mocké (jamais de
dispatch réel depuis un test), amendement `TECH/02` via `contract-change` +
`contract-guardian`.
