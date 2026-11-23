# Console opérateur (application séparée)

Back opérateur des fiches **C0 à C5** de `docs/maquettes-atelier/console.html`.
C'est une **application distincte** : origine propre (son propre nom d'hôte),
jeton propre (secret JWT distinct de `STUDIO_JWT_SECRET`) et déploiement propre.
Elle n'est pas montée par `services/api` et n'importe rien de `studio_api`.

## Garanties

- **Aucune route de lecture de contenu client.** Le service ne lit que des
  agrégats (tailles, compteurs, totaux mesurés) et des identités de studio.
  Aucune route ne touche un projet, un fichier, une note ou un message.
  `tests/operator_console/test_surface.py` gèle la surface exacte.
- **MFA réelle à deux facteurs.** Connexion = adresse + **mot de passe** +
  code TOTP à 6 chiffres. Les mots de passe sont des **hashs bcrypt** en
  configuration serveur, jamais en clair ; la comparaison est à temps constant
  (`bcrypt.checkpw`). Un compte inconnu, un mot de passe faux et une MFA absente
  reçoivent **le même refus générique** (`403 operator_not_allowed`) et
  alimentent le **même compteur d'échecs** (3 essais puis verrouillage 15 min).
- **Enrôlement conforme à la fiche C0.** Un opérateur listé sans secret activé,
  après preuve de son mot de passe, reçoit l'URI `otpauth://`, le secret Base32
  et le **QR en SVG généré côté serveur** (encodeur QR maison, aucune nouvelle
  dépendance). Le secret reste *en attente* tant qu'un premier code à 6 chiffres
  ne l'a pas confirmé ; il est alors écrit hors configuration (fichier d'état).
- **Aucune migration propre au service.** Les tables lues appartiennent au
  cœur : `studios`, `studio_memberships`, `users`, `projects`,
  `usage_ledger_entries`, `infra_measurements`. Le seul écrit est
  `studios.status` + `studios.suspension_reason` (colonne de la migration
  `0050`, voir plus bas) — rien d'autre, aucune suppression, export permis.

## Configuration (préfixe `STUDIO_OPERATOR_`)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://studio:studio@localhost:5432/studio` | cluster partagé |
| `JWT_SECRET` | placeholder refusé en production | secret **propre** de la console, ≥ 32 octets |
| `TOKEN_TTL_MINUTES` | `15` | durée du jeton (1 à 15) |
| `OPERATORS` | `[]` | JSON `[{"email","display_name","password_hash","totp_secret"}]` |
| `SECRETS_PATH` | `.studio-operator-secrets.json` | secrets TOTP activés/en attente (fichier 0600, volume en production) |
| `ENROLLMENT_TTL_MINUTES` | `10` | validité d'un enrôlement en attente |
| `MFA_MAX_ATTEMPTS` / `MFA_LOCKOUT_MINUTES` | `3` / `15` | verrouillage (mot de passe faux inclus) |
| `STORAGE_CAPACITY_BYTES` | 570 Gio | capacité d'illustration (M-seuils, DEC-0387) |
| `STORAGE_ALERT_PERCENT` | `70` | seuil d'alerte C1 |
| `USAGE_ALERT_PERCENT` | `90` | seuil « proche du plafond » C2/C3 |
| `PLAN_QUOTAS` | `{"free":{"storage_bytes":2147483648,"members":5},"pro":{"storage_bytes":107374182400,"members":25}}` | plafonds d'illustration |

Générer un hash de mot de passe (jamais stocker le mot de passe) :

```bash
uv run --package studio-operator python -c \
  "from studio_operator.passwords import hash_password; print(hash_password('…'))"
```

Un opérateur listé **sans** `password_hash` ou **sans** secret TOTP (config ou
fichier d'état) est refusé ; s'il a un mot de passe mais pas encore de secret, il
passe par l'enrôlement QR.

`STUDIO_OPERATOR_ENVIRONMENT=dev|test` autorise le secret de développement.

```bash
uv run --package studio-operator studio-operator   # http://127.0.0.1:8090
```

Le front minimal (`src/studio_operator/static/`) est servi par le même process,
donc à la même origine : aucun CORS, aucun second déploiement pour le squelette.

## Surface

| Méthode | Chemin | Fiche |
|---|---|---|
| `POST` | `/api/v1/auth/mfa` | C0 — adresse + mot de passe + code |
| `POST` | `/api/v1/auth/enrollment` · `/enrollment/confirm` | C0 — QR puis activation |
| `GET` | `/api/v1/auth/me` · `POST /api/v1/auth/logout` | C0 |
| `GET` | `/api/v1/dashboard` | C1 — santé + mesures phase M + compteurs HTTP |
| `GET` | `/api/v1/measures?days=` | C1 — séries phase M |
| `GET` | `/api/v1/studios?q=&limit=` | C2 — liste |
| `GET` | `/api/v1/studios/{id}` | C2 — fiche agrégats |
| `POST`/`DELETE` | `/api/v1/studios/{id}/suspension` | C2 — suspension motivée / réactivation |
| `GET` | `/api/v1/usage?days=` | C3 — usage global, top studios, appels API |
| `GET` | `/api/v1/billing` | C4 — état « non disponible » (S4) |
| `GET` | `/api/v1/suspensions` · `/api/v1/break-glass` | C5 — file des suspensions, break-glass hors périmètre |

Les erreurs suivent l'enveloppe du dépôt : `{"detail": {"error_code", "message"}}`
(401 génériques et 422 de validation exceptés).

## Mesures HTTP (fiche C1/C3)

`services/api` porte un middleware minimal (`HttpMetricsMiddleware`) qui compte,
par heure, **requêtes**, **5xx** et **latence p50/p95**. Un collecteur en
mémoire écrit les heures terminées dans `infra_measurements` (métriques
`http_requests`, `http_requests_5xx`, `http_latency_p50_ms`,
`http_latency_p95_ms`, `subject = "AAAA-MM-JJTHH"`) : aucune table ni migration
supplémentaire. La console agrège ces lignes sur 24 h (taux 5xx, médiane des p50)
et sur la fenêtre d'usage (nombre d'appels). Sondes (`/healthz`, `/readyz`,
`/metrics`, `/version`, docs) exclues ; aucun chemin, corps ou requête n'est
conservé — des nombres seulement.

## Conformité aux maquettes, fiche par fiche

| Fiche | Verdict | Écart et raison |
|---|---|---|
| **C0** connexion et MFA | **conforme** | Maquette révisée (seule modification autorisée) : adresse, mot de passe, code à 6 chiffres. Refus générique, verrouillage avec essais restants, chargement, session expirée. |
| C0 · « Vide · première connexion, configuration MFA » | **conforme** | Enrôlement QR réel : cadre QR, code à 6 chiffres, bouton « Activer » ; le QR et le secret restent en attente jusqu'au premier code valide. |
| **C1** tableau de bord | **conforme** | Studios actifs, stockage et seuil d'alerte, **erreurs 5xx (24 h)** réelles, latence médiane réelle, état par service, états vide/chargement/erreur. |
| C1 · impayés en grâce | **différent** | S4-Stripe non déployé : « — / S4 non déployé » plutôt qu'un chiffre inventé. |
| **C2** studios (liste, fiche, suspension) | **conforme** | Colonnes et libellés identiques ; quota stockage/membres par plan ; suspension avec **motif obligatoire, stocké et affiché** ; états vide/chargement/erreur/limite. |
| C2 · identifiant de cellule | **différent** | UUID court (`11111111…`) au lieu de `stu_a91…` : le schéma n'a pas d'identifiant court de studio. |
| **C3** usage | **conforme, un reste** | Stockage plateforme, **appels API réels** (compteur horaire), top studios et mesures phase M (jetons, durée, coût par devise) ; « Envois (volume) » reste « non mesuré » (pas de volume d'envois agrégé par heure — voir plus bas). |
| **C4** facturation | **conforme** | Fiche S4 non déployée : état « non disponible » explicite, aucune lecture d'abonnement/impayé/webhook, jamais de donnée de carte. |
| **C5** suspensions et break-glass | **partiel** | File des suspensions livrée (motif, depuis, réactivation). Break-glass hors périmètre (`2d4927e6`) : route et vue répondent `available=false`, rien n'est lu ni écrit. |

## Changements côté cœur (services/api)

- **Migration `0051_studio_suspension_reason`** (`down_revision = "0050"`,
  réversible) : ajoute `studios.suspension_reason` (texte, nullable). Une autre
  branche peut ajouter une tête en parallèle — la fusion des têtes est laissée
  à l'orchestrateur.
- `StudioModel.suspension_reason` et `StudioRead` (`routers/users.py`).
- `GET /api/v1/studio` : studio actif du demandeur (tout membre), avec
  `suspension_reason` pour que la vue N5 côté client explique la suspension.
- Compteurs HTTP par heure et persistance via `infra_measurements` (ci-dessus).

## Reste à faire

- « Envois (volume) » (C3) : nécessite un volume de transferts agrégé par
  période ; non dérivé des mesures actuelles (DISCOVERY).
- Facturation (S4-Stripe) et demandes break-glass : à brancher quand leurs
  services existent.
- Déploiement réel (Dockerfile/compose/Caddy) volontairement non ajouté pour
  ne pas toucher l'infrastructure partagée : la console se déploie comme un
  process séparé, derrière son propre nom d'hôte, avec `SECRETS_PATH` sur un
  volume persistant.
