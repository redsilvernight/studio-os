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
- **MFA obligatoire.** Un opérateur vient de la configuration serveur
  (`STUDIO_OPERATOR_OPERATORS`) et n'entre que s'il a un secret TOTP. Un
  opérateur listé sans MFA est refusé comme un inconnu (même enveloppe, aucun
  détail). Trois codes faux verrouillent le compte 15 min (paramétrable).
- **Aucune migration, aucune table propre.** Les tables lues appartiennent au
  cœur : `studios`, `studio_memberships`, `users`, `projects`,
  `usage_ledger_entries`, `infra_measurements`. Le seul écrit est
  `studios.status` pour la suspension (`suspended` / `active`) — rien d'autre,
  aucune suppression, export toujours permis.

## Configuration (préfixe `STUDIO_OPERATOR_`)

| Variable | Défaut | Rôle |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://studio:studio@localhost:5432/studio` | cluster partagé |
| `JWT_SECRET` | placeholder refusé en production | secret **propre** de la console, ≥ 32 octets |
| `TOKEN_TTL_MINUTES` | `15` | durée du jeton (1 à 15) |
| `OPERATORS` | `[]` | JSON `[{"email","display_name","totp_secret"}]` ; `totp_secret` absent ⇒ refus |
| `MFA_MAX_ATTEMPTS` / `MFA_LOCKOUT_MINUTES` | `3` / `15` | verrouillage après codes faux |
| `STORAGE_CAPACITY_BYTES` | 570 Gio | capacité d'illustration (M-seuils, DEC-0387) |
| `STORAGE_ALERT_PERCENT` | `70` | seuil d'alerte C1 |
| `USAGE_ALERT_PERCENT` | `90` | seuil « proche du plafond » C2/C3 |
| `PLAN_QUOTAS` | `{"free":{"storage_bytes":2147483648,"members":5},"pro":{"storage_bytes":107374182400,"members":25}}` | plafonds d'illustration |

`STUDIO_OPERATOR_ENVIRONMENT=dev|test` autorise le secret de développement.

```bash
uv run --package studio-operator studio-operator   # http://127.0.0.1:8090
```

Le front minimal (`src/studio_operator/static/`) est servi par le même process,
donc à la même origine : aucun CORS, aucun second déploiement pour le squelette.

## Surface

| Méthode | Chemin | Fiche |
|---|---|---|
| `POST` | `/api/v1/auth/mfa` | C0 — connexion + MFA |
| `GET` | `/api/v1/auth/me` · `POST /api/v1/auth/logout` | C0 |
| `GET` | `/api/v1/dashboard` | C1 — santé + mesures phase M |
| `GET` | `/api/v1/measures?days=` | C1 — séries phase M |
| `GET` | `/api/v1/studios?q=&limit=` | C2 — liste |
| `GET` | `/api/v1/studios/{id}` | C2 — fiche agrégats |
| `POST`/`DELETE` | `/api/v1/studios/{id}/suspension` | C2 — suspension / réactivation |
| `GET` | `/api/v1/usage?days=` | C3 — usage global + top studios |
| `GET` | `/api/v1/billing` | C4 — état « non disponible » (S4) |
| `GET` | `/api/v1/suspensions` · `/api/v1/break-glass` | C5 — file des suspensions, break-glass hors périmètre |

Les erreurs suivent l'enveloppe du dépôt : `{"detail": {"error_code", "message"}}`
(401 génériques et 422 de validation exceptés).

## Conformité aux maquettes, fiche par fiche

| Fiche | Verdict | Écart et raison |
|---|---|---|
| **C0** connexion et MFA | conforme, un ajout | Champ « Adresse professionnelle » ajouté : la maquette ne saisit que le code, mais la configuration identifie l'opérateur par adresse. États : chargement, code incorrect (essais restants), verrouillage, refus générique, session expirée. |
| C0 · état « première connexion, configuration MFA » (QR) | **différent** | L'enrôlement est hors périmètre par construction : les secrets TOTP vivent en configuration serveur, et un opérateur sans MFA est refusé (exigence explicite). Le front affiche à la place le renvoi vers l'administrateur. |
| **C1** tableau de bord | conforme | KPI, alertes de seuil, état par service, états vide/chargement/erreur. |
| C1 · erreurs 5xx, latence API, impayés | **différent** | Aucune source de mesure n'existe pour ces trois chiffres : ils sont rendus « — / non mesuré » au lieu d'une valeur inventée. |
| **C2** studios (liste, fiche, suspension) | conforme | Colonnes et libellés identiques ; quota stockage/membres par plan ; suspension avec motif obligatoire ; états vide/chargement/erreur/limite. |
| C2 · badge « Suspendu · impayé » | **différent** | Le motif n'est pas stocké (aucune colonne, aucune migration ici) : le badge dit « Suspendu ». Voir TODO. |
| C2 · identifiant de cellule | **différent** | UUID court (`11111111…`) au lieu de `stu_a91…` : le schéma actuel n'a pas d'identifiant court de studio. |
| **C3** usage | conforme, partiel | Stockage plateforme et top studios conformes ; les tuiles « Envois (volume) » et « Appels API » n'ont pas de source agrégée et affichent « non mesuré ». Les mesures phase M réellement disponibles (jetons, durée, coût par devise) sont ajoutées dans un bloc dédié. |
| **C4** facturation | conforme | Fiche S4 non déployée : état « non disponible » explicite, aucune lecture d'abonnement/impayé/webhook, jamais de donnée de carte. |
| **C5** suspensions et break-glass | **partiel** | La file des suspensions est livrée (liste + réactivation). Les demandes break-glass relèvent de la tâche `2d4927e6` : route et vue répondent `available=false`, rien n'est lu ni écrit. |

## Reste à faire (hors périmètre de cette tâche)

- **Motif de suspension non persisté** : `studios` n'a pas de colonne dédiée.
  Il est journalisé par la console ; une migration isolée (colonne motif +
  auteur, côté workstream studios) est nécessaire pour que le propriétaire le
  voie comme sur la maquette.
- Facturation (S4-Stripe) et demandes break-glass : à brancher quand leurs
  services existent.
- Déploiement réel (Dockerfile/compose/Caddy) volontairement non ajouté pour
  ne pas toucher l'infrastructure partagée : la console se déploie comme un
  process séparé, derrière son propre nom d'hôte.
