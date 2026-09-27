# DEC-0126 — Licence du dépôt : Apache-2.0 + inventaire tiers embarqué

Statut : `accepted` (choix humain exprimé en session B3 du 2026-09-26, accepté
le 2026-09-26 — fichier et serveur alignés).

## Décision

Le dépôt Studio OS est publié sous **Apache License 2.0** (`LICENSE` à la racine).
Apache-2.0 comme MIT sont gratuites ; Apache-2.0 est retenue pour sa clause de
licence de brevets, compatible avec l'écosystème du sidecar (dominante
MIT/Apache-2.0, voir inventaire ci-dessous).

## Inventaire tiers (B3)

- `desktop/scripts/notices.mjs --check` génère `THIRD_PARTY_INVENTORY.json` dans
  le sidecar à chaque build : 332 paquets au 2026-09-26 (python 25, rust 306,
  npm 1), **0 sans licence déclarée, 0 copyleft non relu**.
- Copyleft relu et accepté : 6 crates MPL-2.0 liées statiquement sans
  modification (`cssparser`, `cssparser-macros`, `dtoa-short`, `option-ext`,
  `selectors`, +1) — cf. `REVIEWED_COPYLEFT` dans `notices.mjs`.
- Ce n'est pas un SBOM certifié ni un avis juridique (mention portée par
  l'inventaire lui-même et `DESKTOP_P10_PACKAGING.md` §13).

## Reste bloquant avant diffusion publique

- Valider la mention copyright (`Copyright 2026 redsilvernight` par défaut).
- `DESKTOP_P10_PACKAGING.md` §13/§15 mis à jour par B3 (plus de mention
  « pas de fichier LICENSE »).
