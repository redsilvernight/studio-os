---
id: DEC-0060
title: 'Etape 9.3 : revue de securite, durcissement headers au edge'
status: active
date: '2026-09-16'
superseded_by: null
source: docs/DECISIONS.md
---

# DEC-0060 — Etape 9.3 : revue de securite, durcissement headers au edge

Point 3 du « Travail attendu » de l'étape 9 de
`docs/ROADMAP_CORRECTIONS_AUDIT.md` (« Observabilité, rate limiting et revue
de sécurité »). L'observabilité (`/metrics`, logs JSON, `tests/api/test_middleware.py`)
et le rate limiting (bucket in-memory, bucket webhook dédié DEC-0059) sont
déjà livrés et cochés dans `IMPLEMENTATION/04_INTEGRATION_CHECKLIST.md`.
Restait la revue de sécurité formelle : constats ci-dessous, gaps fermés au
edge, le tout sans changement de contrat (aucun amendement `TECH/02-05`,
aucune migration).

## Constats (conformes, sans changement)

| Domaine | Verdict | Preuve |
|---|---|---|
| Webhook GitHub HMAC | CONFORME | Corps borné 1 Mio + secret manquant → 503 (`routers/github.py:34-90`) ; comparaison `hmac.compare_digest` timing-safe, secret ni loggé ni retourné (`services/github.py:31-42`) |
| CORS | CONFORME | Deny-by-default (`cors_origins=""`, `settings.py:29`), middleware monté seulement si configuré (`middleware.py:171-182`) ; test `test_cors_not_configured_by_default` |
| JWT dashboard | CONFORME + DURCI | HS256, `exp` 480 min, bcrypt côté provisioning (`jwt_auth.py`, `provisioning.py:71-76`) ; warning de démarrage élargi au secret par défaut **et** aux secrets < 32 octets (RFC 7518 §3.2, `is_weak_jwt_secret`, `main.py:138-143`), constaté via `InsecureKeyLengthWarning` en suite de tests |
| Rate limiting | CONFORME V1 | Token-bucket in-memory, clé = hash du Bearer puis X-Forwarded-For (`middleware.py:58-168`) ; mono-nœud compose, un store partagé n'est pas requis (docstring l.65-68) |
| Secrets | CONFORME | `.env` ignoré (`gitignore:23`), seuls des placeholders dans les `.env.example`, compose par `${...}` uniquement |
| CI | CONFORME | Identifiants Postgres/MinIO en clair limités aux services éphémères CI (`ci.yml:46-99`), aucun `${{ secrets.* }}` requis |

## Décision

1. **HSTS + baseline au edge Caddy** (`docker/Caddyfile`) sur les 4 sites
   terminés en TLS (API, MCP, dashboard, storage) : `Strict-Transport-Security:
   max-age=31536000` (sans `includeSubDomains`, périmètre minimal),
   `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (API/MCP/storage)
   ou `SAMEORIGIN` (dashboard SPA, pour ne pas casser un usage same-origin
   légitime), `Referrer-Policy: strict-origin-when-cross-origin`.
2. **Catch-all `:80` (Tailscale Funnel, HTTP clair) exclu** : HSTS sur HTTP
   est ignoré par spécification ; les headers applicatifs restent posés par
   `SecurityHeadersMiddleware` côté API.
3. **Headers nginx dashboard** (`docker/dashboard.nginx.conf`) en défense en
   profondeur (nosniff + SAMEORIGIN + referrer-policy, répétés dans
   `location /assets/` car `add_header` y désactive l'héritage). Pas de CSP :
   non vérifiable sans build navigateur dans cette passe, et un CSP faux
   casserait la SPA ; réévalué quand le dashboard aura un test CSP dédié.
4. **Pas de durcissement JWT/rate-limit dans ce lot** : le warning secret
   par défaut et le bucket in-memory sont documentés et suffisants pour le
   V1 mono-nœud ; les changer (refus de démarrage, Redis partagé) serait un
   choix d'exploitation, pas un correctif de sécurité.

## Preuves

- `docker run --rm caddy:2-alpine caddy validate --adapter caddyfile --config docker/Caddyfile`
  (avec les 4 domaines en variables d'environnement) vert.
- `nginx -t` sur `docker/dashboard.nginx.conf` vert (image dashboard locale).
- `uv run pytest tests/api/test_middleware.py tests/api/test_auth.py -q` → 12 passed (comportement API inchangé + helper `is_weak_jwt_secret`).
- `uv run ruff check .` + `uv run ruff format --check .` verts (Caddyfile/nginx hors périmètre ruff, relus à la main).

## Hors périmètre

- 9.1c (dispatch `workflow_dispatch`) : toujours différé par DEC-0059, aucun
  besoin réel exprimé.
- Rate limiting distribué : non requis tant que le déploiement reste le
  compose mono-nœud (invariant documenté dans `middleware.py:65-68`).
- Rotation/révocation périodique : déjà couverte (9.5, `docker/revoke-machine.sh`,
  `STUDIO_JWT_SECRET`, checklist cochée).
