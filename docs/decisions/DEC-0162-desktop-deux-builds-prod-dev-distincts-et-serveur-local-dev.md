---
id: DEC-0162
title: 'Desktop : deux builds Prod/Dev distincts et serveur local Dev'
status: accepted
date: '2026-10-08'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0162 — Desktop : deux builds Prod/Dev distincts et serveur local Dev

## Contexte

La promotion beta vers stable de DEC-0137 republiait les mêmes octets sous
`desktop-dev` et `desktop-prod`. L'installeur stable gardait donc l'identité
Tauri Dev et son origine API. Cette propriété empêche d'installer une vraie Prod
et une vraie Dev côte à côte lorsque Dev doit parler à une instance locale et
Prod à l'instance Flo-laptop.

## Décision

1. Un push sur `dev` construit `desktop-dev` avec `--channel dev`, l'identité
   `dev.studio-os.desktop-dev`, les données `StudioOS-Dev` et une origine
   loopback.
2. Un push sur `deploy/flo-laptop` construit `desktop-prod` avec
   `--channel prod`, l'identité `stable.studio-os.desktop`, les données `StudioOS`
   et l'origine HTTPS configurée dans l'environnement GitHub `desktop-prod`.
   L'origine compilée de chaque canal est fixe ; les anciens overrides locaux
   ne peuvent pas reconnecter Dev à Prod ni Prod à une autre instance.
3. Les deux releases vivantes conservent la publication non destructive : le
   tag est déplacé avant l'édition de la release, et l'ancienne release reste
   téléchargeable si la publication échoue.
4. Une restauration réutilise uniquement un artefact antérieur du même canal.
   Toute promotion croisée Dev/Prod est refusée.
5. Le Desktop Dev démarre une stack locale isolée en réutilisant les services et
   images Docker Studio OS. Les ports sont liés au loopback et Prod ne démarre
   jamais cette stack.

## Conséquences

- Les artefacts Dev et Prod ont volontairement des SHA-256 différents.
- Chaque canal possède son propre flux updater et sa propre suite de versions.
- Le changement abandonne `REBUILD_NEVER_TRUSTED` entre les canaux vivants : la
  confiance vient désormais d'un build reproductible, signé et rattaché au SHA
  exact de la branche source.
- Docker Desktop est une dépendance explicite de la distribution Dev locale,
  jamais de la distribution Prod.
- L'identité Prod est `stable.studio-os.desktop` (service de coffre
  `stable.studio-os.desktop.session`), et non plus `dev.studio-os.desktop` qui
  prêtait à confusion avec Dev. Les installations Prod héritées de DEC-0137
  (0.1.0) ne migrent pas leurs réglages ni leur session : réinstallation et
  reconnexion. La première release Prod native est la 0.5.0.
- DEC-0137 reste l'historique du mécanisme remplacé et est supersédée.
