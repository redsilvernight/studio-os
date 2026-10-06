# Baseline P00 — numérotation des DEC (fichiers vs serveur)
Rapport chiffré et reproductible de l'écart de numérotation entre les ADR
fichiers de `docs/decisions/` et les DEC enregistrées côté serveur. Le côté
serveur est un snapshot figé (`docs/DEC_BASELINE_P00.json`), lu via l'outil MCP
`studio_get_decisions` (lecture seule).
Reproduire / vérifier ce rapport :

```
uv run python -m scripts.dec_baseline --root . --check
uv run python -m scripts.dec_baseline --root . --apply
```
## Snapshot serveur
- Source : `studio_get_decisions (Studio OS MCP, read-only)`
- Format : `studio.dec-baseline.server-snapshot/v1`
- Portée projet : `2a836038-153c-41cf-879a-73bd794760b0`
- Entrées : 188
- Empreinte : `sha256:cf4fc39f442be2f91870b6420ae227120cffdd9d9313153833dd84d39e40ad3d`
## Fichiers `docs/decisions/`
- ADR fichiers : **155** (149 nommés `DEC-XXXX-*.md`, 6 nommés autrement)
- Identifiants DEC couverts : **155**
- Numéro max : **187** (min 1)
- Trous : **32**
- Doublons : **0**
- ADR sans identifiant DEC : **0**
- Discordance fichier/front matter : **0**
### ADR nommés autrement (identifiant via `server_readable_id`)
Ces ADR ne suivent pas le motif `DEC-XXXX-*.md` mais portent leur
identifiant DEC dans `server_readable_id` : ils comptent comme
correspondances fichiers ↔ serveur.
- `DU0-C-trusted-proxy-rate-limiting.md` → `DEC-0106`
- `DU0-D-version-compatibility.md` → `DEC-0107`
- `DU0-E-release-signature-distribution.md` → `DEC-0108`
- `DU0-A-public-registration.md` → `DEC-0109`
- `DU0-B-session-revocation.md` → `DEC-0110`
- `AIB-P9-launch-credential.md` → `DEC-0182`
## Chiffres
| Métrique | Fichiers | Serveur (global) | Serveur (projet) |
|---|---|---|---|
| Numéro max | 187 | 191 | 191 |
| Nombre de DEC | 155 | 188 | 159 |
| Trous | 32 | 3 | 32 |
| Doublons | 0 | 0 | — |

## Trous de numérotation
- Fichiers : `DEC-0083`, `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0114`, `DEC-0115`, `DEC-0116`, `DEC-0117`, `DEC-0118`, `DEC-0119`, `DEC-0120`, `DEC-0121`, `DEC-0122`, `DEC-0123`, `DEC-0124`, `DEC-0125`, `DEC-0128`, `DEC-0131`, `DEC-0136`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0153`, `DEC-0158`, `DEC-0165`, `DEC-0166`, `DEC-0169`, `DEC-0170`, `DEC-0174`, `DEC-0178`, `DEC-0183`, `DEC-0184`
- Serveur global : `DEC-0092`, `DEC-0166`, `DEC-0174`
- Serveur projet : `DEC-0092`, `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0126`, `DEC-0132`, `DEC-0133`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0143`, `DEC-0144`, `DEC-0145`, `DEC-0146`, `DEC-0147`, `DEC-0148`, `DEC-0149`, `DEC-0150`, `DEC-0151`, `DEC-0152`, `DEC-0153`, `DEC-0154`, `DEC-0155`, `DEC-0166`, `DEC-0169`, `DEC-0170`, `DEC-0171`, `DEC-0174`, `DEC-0178`, `DEC-0187`, `DEC-0188`, `DEC-0189`
## Écart fichiers ↔ serveur
### Portée globale (toutes les DEC serveur)
- Présents en fichier seulement : `DEC-0092`
- Présents au serveur seulement : `DEC-0083`, `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0114`, `DEC-0115`, `DEC-0116`, `DEC-0117`, `DEC-0118`, `DEC-0119`, `DEC-0120`, `DEC-0121`, `DEC-0122`, `DEC-0123`, `DEC-0124`, `DEC-0125`, `DEC-0128`, `DEC-0131`, `DEC-0136`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0153`, `DEC-0158`, `DEC-0165`, `DEC-0169`, `DEC-0170`, `DEC-0178`, `DEC-0183`, `DEC-0184`, `DEC-0188`, `DEC-0189`, `DEC-0190`, `DEC-0191`
### Portée projet (`project_scope_id`)
- Présents en fichier seulement : `DEC-0092`, `DEC-0126`, `DEC-0132`, `DEC-0133`, `DEC-0143`, `DEC-0144`, `DEC-0145`, `DEC-0146`, `DEC-0147`, `DEC-0148`, `DEC-0149`, `DEC-0150`, `DEC-0151`, `DEC-0152`, `DEC-0154`, `DEC-0155`, `DEC-0171`, `DEC-0187`
- Présents au serveur seulement : `DEC-0083`, `DEC-0114`, `DEC-0115`, `DEC-0116`, `DEC-0117`, `DEC-0118`, `DEC-0119`, `DEC-0120`, `DEC-0121`, `DEC-0122`, `DEC-0123`, `DEC-0124`, `DEC-0125`, `DEC-0128`, `DEC-0131`, `DEC-0136`, `DEC-0158`, `DEC-0165`, `DEC-0183`, `DEC-0184`, `DEC-0190`, `DEC-0191`
- DEC serveur hors portée projet (project_id null ou autre) : 29 — `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0126`, `DEC-0132`, `DEC-0133`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0143`, `DEC-0144`, `DEC-0145`, `DEC-0146`, `DEC-0147`, `DEC-0148`, `DEC-0149`, `DEC-0150`, `DEC-0151`, `DEC-0152`, `DEC-0153`, `DEC-0154`, `DEC-0155`, `DEC-0169`, `DEC-0170`, `DEC-0171`, `DEC-0178`, `DEC-0187`, `DEC-0188`, `DEC-0189`
