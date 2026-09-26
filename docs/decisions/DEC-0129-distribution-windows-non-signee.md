# DEC-0129 — Distribution Windows non signée : pas de certificat Authenticode (coût)

Statut : `proposed` (choix humain exprimé en session du 2026-09-26 — fichier et
serveur alignés sur `proposed` jusqu'à accord explicite).

## Décision

Aucun certificat de signature de code ne sera acheté (coût refusé). Il n'existe
pas d'alternative gratuite à Authenticode de confiance : Let's Encrypt ne signe
pas de code, un certificat auto-signé échoue `signtool verify /pa` et ne passe
pas Smart App Control, Azure Trusted Signing est lui aussi payant.

## Conséquences

- L'installateur NSIS est distribué **non signé** : Windows SmartScreen avertit
  à l'installation, Smart App Control peut bloquer. C'est assumé, pas un bug.
- La confiance repose sur : signatures minisign de l'updater (clé publique
  compilée, artefact altéré ou mal signé refusé avant installation),
  `SHA256SUMS.txt` + `provenance.json` par release (B3), canal HTTPS du
  manifeste.
- La plomberie Authenticode livrée par B4 (`desktop/scripts/windows-signing.mjs`,
  overlay `bundle.windows`, gate `--verify`) reste en place mais **dormante** :
  elle ne s'active que si un certificat arrive un jour (secrets
  `WINDOWS_CERT_THUMBPRINT` ou `WINDOWS_SIGN_PFX_BASE64` + `WINDOWS_SIGN_PASSWORD`).
  En attendant, `desktop-release.yml` ne pose pas `STUDIO_REQUIRE_AUTHENTICODE=1`
  et la vérification est en mode rapport (un build non signé passe, un build à
  moitié signé reste détectable).
- Les critères B4 « `signtool verify` sur les livrés » et « installation propre
  sous Smart App Control (A14) » sont **inatteignables** dans ce modèle : la
  roadmap doit être amendée par un humain (re-scoper ou exempter B4), un agent
  ne réécrit pas les critères d'acceptation.
- Les trois tâches B1 (choix fournisseur, garde de clé, validation d'identité)
  sont closes avec le motif « refusé : coût ».

## Source

Travail B4 : branche `task/desktop-distribution-public-registration/B4-70f863d9-signing`.
