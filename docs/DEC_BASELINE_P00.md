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
- ADR fichiers : **220** (220 nommés `DEC-XXXX-*.md`, 0 nommés autrement)
- Identifiants DEC couverts : **220**
- Numéro max : **251** (min 1)
- Trous : **31**
- Doublons : **0**
- ADR sans identifiant DEC : **0**
- Discordance fichier/front matter : **0**
## Chiffres
| Métrique | Fichiers | Serveur (global) | Serveur (projet) |
|---|---|---|---|
| Numéro max | 251 | 191 | 191 |
| Nombre de DEC | 220 | 188 | 159 |
| Trous | 31 | 3 | 32 |
| Doublons | 0 | 0 | — |

## Trous de numérotation
- Fichiers : `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0153`, `DEC-0166`, `DEC-0169`, `DEC-0170`, `DEC-0174`, `DEC-0178`, `DEC-0188`, `DEC-0189`, `DEC-0203`, `DEC-0204`, `DEC-0207`, `DEC-0208`, `DEC-0226`, `DEC-0227`, `DEC-0228`, `DEC-0229`, `DEC-0230`, `DEC-0231`, `DEC-0232`, `DEC-0233`, `DEC-0234`, `DEC-0236`, `DEC-0245`, `DEC-0246`, `DEC-0247`
- Serveur global : `DEC-0092`, `DEC-0166`, `DEC-0174`
- Serveur projet : `DEC-0092`, `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0126`, `DEC-0132`, `DEC-0133`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0143`, `DEC-0144`, `DEC-0145`, `DEC-0146`, `DEC-0147`, `DEC-0148`, `DEC-0149`, `DEC-0150`, `DEC-0151`, `DEC-0152`, `DEC-0153`, `DEC-0154`, `DEC-0155`, `DEC-0166`, `DEC-0169`, `DEC-0170`, `DEC-0171`, `DEC-0174`, `DEC-0178`, `DEC-0187`, `DEC-0188`, `DEC-0189`
## Écart fichiers ↔ serveur
### Portée globale (toutes les DEC serveur)
- Présents en fichier seulement : `DEC-0092`, `DEC-0192`, `DEC-0193`, `DEC-0194`, `DEC-0195`, `DEC-0196`, `DEC-0197`, `DEC-0198`, `DEC-0199`, `DEC-0200`, `DEC-0201`, `DEC-0202`, `DEC-0205`, `DEC-0206`, `DEC-0209`, `DEC-0210`, `DEC-0211`, `DEC-0212`, `DEC-0213`, `DEC-0214`, `DEC-0215`, `DEC-0216`, `DEC-0217`, `DEC-0218`, `DEC-0219`, `DEC-0220`, `DEC-0221`, `DEC-0222`, `DEC-0223`, `DEC-0224`, `DEC-0225`, `DEC-0235`, `DEC-0237`, `DEC-0238`, `DEC-0239`, `DEC-0240`, `DEC-0241`, `DEC-0242`, `DEC-0243`, `DEC-0244`, `DEC-0248`, `DEC-0249`, `DEC-0250`, `DEC-0251`
- Présents au serveur seulement : `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0153`, `DEC-0169`, `DEC-0170`, `DEC-0178`, `DEC-0188`, `DEC-0189`
### Portée projet (`project_scope_id`)
- Présents en fichier seulement : `DEC-0092`, `DEC-0126`, `DEC-0132`, `DEC-0133`, `DEC-0143`, `DEC-0144`, `DEC-0145`, `DEC-0146`, `DEC-0147`, `DEC-0148`, `DEC-0149`, `DEC-0150`, `DEC-0151`, `DEC-0152`, `DEC-0154`, `DEC-0155`, `DEC-0171`, `DEC-0187`, `DEC-0192`, `DEC-0193`, `DEC-0194`, `DEC-0195`, `DEC-0196`, `DEC-0197`, `DEC-0198`, `DEC-0199`, `DEC-0200`, `DEC-0201`, `DEC-0202`, `DEC-0205`, `DEC-0206`, `DEC-0209`, `DEC-0210`, `DEC-0211`, `DEC-0212`, `DEC-0213`, `DEC-0214`, `DEC-0215`, `DEC-0216`, `DEC-0217`, `DEC-0218`, `DEC-0219`, `DEC-0220`, `DEC-0221`, `DEC-0222`, `DEC-0223`, `DEC-0224`, `DEC-0225`, `DEC-0235`, `DEC-0237`, `DEC-0238`, `DEC-0239`, `DEC-0240`, `DEC-0241`, `DEC-0242`, `DEC-0243`, `DEC-0244`, `DEC-0248`, `DEC-0249`, `DEC-0250`, `DEC-0251`
- Présents au serveur seulement : —
- DEC serveur hors portée projet (project_id null ou autre) : 29 — `DEC-0111`, `DEC-0112`, `DEC-0113`, `DEC-0126`, `DEC-0132`, `DEC-0133`, `DEC-0138`, `DEC-0139`, `DEC-0140`, `DEC-0143`, `DEC-0144`, `DEC-0145`, `DEC-0146`, `DEC-0147`, `DEC-0148`, `DEC-0149`, `DEC-0150`, `DEC-0151`, `DEC-0152`, `DEC-0153`, `DEC-0154`, `DEC-0155`, `DEC-0169`, `DEC-0170`, `DEC-0171`, `DEC-0178`, `DEC-0187`, `DEC-0188`, `DEC-0189`
