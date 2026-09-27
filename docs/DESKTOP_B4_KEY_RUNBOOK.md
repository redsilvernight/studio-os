# B4 — Runbook de rotation et de révocation des clés Desktop

Ce runbook traite séparément la clé de mise à jour Tauri/minisign et le
certificat Authenticode. Ces deux mécanismes ne sont ni interchangeables ni
stockés ensemble.

État courant : la signature minisign de l'updater est le mécanisme de confiance
actif. Authenticode reste dormant conformément à DEC-0129 : aucun certificat
n'est acheté, les exécutables Windows sont distribués non signés et SmartScreen
ou Smart App Control peuvent les avertir ou les bloquer.

## Inventaire et responsabilités

| Élément | Secret CI | Partie publique | Rôle |
|---|---|---|---|
| Clé updater minisign | `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | `STUDIO_UPDATER_PUBKEY`, compilée dans le Desktop | Authentifier l'artefact téléchargé |
| Certificat Authenticode | `WINDOWS_SIGN_PFX_BASE64`, `WINDOWS_SIGN_PASSWORD`, ou certificat déjà installé désigné par `WINDOWS_CERT_THUMBPRINT` | Chaîne X.509 et horodatage | Authentifier l'éditeur auprès de Windows |

Les secrets vivent uniquement dans l'environnement GitHub protégé
`desktop-release`. Ils ne sont jamais copiés dans le dépôt, un artefact de
workflow, un log, `SHA256SUMS.txt` ou `provenance.json`. Deux personnes doivent
valider toute rotation ou révocation en production : l'opérateur et le
relecteur. Le journal d'incident ou de rotation ne contient que les empreintes
publiques, versions et identifiants de runs.

## Générer et enregistrer une clé updater

Depuis `desktop/`, dans PowerShell et sur un poste de confiance :

```powershell
npx tauri signer generate -w <chemin-hors-depot>\studio-updater.key
```

1. Conserver la clé privée et son mot de passe dans deux emplacements de
   récupération chiffrés distincts.
2. Enregistrer le contenu privé dans `TAURI_SIGNING_PRIVATE_KEY`, son mot de
   passe dans `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, et la clé publique dans
   `STUDIO_UPDATER_PUBKEY`.
3. Noter l'empreinte de la clé publique, jamais la clé privée, dans le compte
   rendu de rotation.
4. Exécuter un build de release privé. Vérifier que l'artefact `.sig` existe et
   que le test updater accepte la release signée mais refuse une signature ou
   un artefact altéré.

Perdre la clé privée empêche de publier une mise à jour acceptée par les clients
qui possèdent sa clé publique. Une sauvegarde récupérable est donc obligatoire.

## Rotation planifiée de la clé updater

Notations : K1 est la clé active, K2 sa remplaçante, M la version-pont.

1. Générer K2 et sauvegarder sa partie privée avant toute modification CI.
2. Construire M avec la **clé publique K2** dans `STUDIO_UPDATER_PUBKEY`, mais
   signer l'artefact M avec la **clé privée K1** dans
   `TAURI_SIGNING_PRIVATE_KEY`. Les clients existants font confiance à K1 et
   peuvent installer M ; après installation, M fait confiance à K2.
3. Vérifier sur une installation portant K1 que M est acceptée, puis qu'un
   artefact de test signé par K2 est accepté par M. Vérifier aussi les refus
   d'une signature K1 après migration, d'une signature inconnue et d'un
   artefact altéré.
4. Publier M sur chaque canal supporté et conserver sa signature K1, son hash et
   sa provenance pendant toute la période de migration.
5. Le service de manifeste doit imposer M comme étape intermédiaire aux clients
   antérieurs à M. Un manifeste statique unique ne permet pas de servir en même
   temps une release K1 aux anciens clients et une release K2 aux clients déjà
   migrés : tant que ce routage n'est pas démontré, ne pas retirer K1.
6. Une fois la migration démontrée, remplacer le secret privé K1 par K2,
   construire la release suivante avec K2 public + privé, puis refaire les
   tests d'acceptation et de refus.
7. Retirer K1 du CI. Conserver sa sauvegarde chiffrée pendant la fenêtre de
   support N/N-1, puis la détruire avec une preuve datée approuvée par les deux
   personnes. La clé publique et les artefacts historiques restent publics.

Ne jamais reconstruire M pour la promotion beta vers stable : promouvoir le
même artefact et le même fichier `.sig` par le manifeste.

## Compromission ou perte de la clé updater

Si la clé K1 est soupçonnée compromise :

1. Suspendre immédiatement les manifests de mise à jour et les releases ; ne
   pas publier une version-pont signée par K1 comme si elle rétablissait la
   confiance.
2. Révoquer l'accès au secret CI, renouveler les accès GitHub concernés et
   préserver les journaux. Identifier la première date possible de
   compromission et les versions construites depuis cette date.
3. Générer K2 sur un poste propre, reconstruire depuis un commit audité et
   publier les hashes, la provenance et l'avis d'incident par un canal
   authentifié indépendant de l'updater.
4. Les clients qui ne possèdent que la clé publique K1 doivent réinstaller une
   version portant K2 depuis ce canal indépendant. Une signature produite avec
   K1 après compromission ne peut pas établir la confiance dans K2.
5. Ne rouvrir le manifeste qu'après validation de l'installation propre, du
   refus des artefacts K1 et altérés, et de la récupération N/N-1.

Si K1 est seulement perdue mais non compromise, les clients existants ne
peuvent néanmoins plus recevoir de nouvelle release. Appliquer le même parcours
de réinstallation, sans qualifier l'événement d'incident de sécurité.

## Authenticode — activation future uniquement

L'activation exige une décision humaine qui remplace DEC-0129 et un certificat
RSA de signature de code émis par un fournisseur approuvé par Windows. Avant la
première release signée :

1. Stocker le PFX et son mot de passe dans les secrets `desktop-release`, ou
   installer le certificat et renseigner son empreinte SHA-1.
2. Définir `STUDIO_REQUIRE_AUTHENTICODE=1` dans le job de release et exécuter la
   vérification avec `windows-signing.mjs --verify --require`.
3. Conserver l'horodatage RFC 3161 et SHA-256. Authenticode doit être appliqué
   pendant `tauri build`, avant la signature updater, jamais après.
4. Vérifier l'installeur, l'application, `studio-daemon.exe`, les binaires
   sidecar, le désinstalleur et tous les exécutables temporaires, puis exécuter
   le scénario Smart App Control sur une installation Windows propre.

### Rotation planifiée du certificat

1. Obtenir et valider le nouveau certificat avant l'expiration de l'ancien.
2. Remplacer le PFX et son mot de passe dans une même fenêtre de maintenance,
   ou remplacer `WINDOWS_CERT_THUMBPRINT` si le certificat est préinstallé.
3. Produire un candidat privé avec le mode fail-closed actif ; vérifier chaque
   exécutable avec `signtool verify /pa /v` et archiver le run, les empreintes
   publiques et les résultats.
4. Publier seulement après le test d'installation, d'update et de
   désinstallation. Ne pas supprimer l'ancien secret avant que le nouveau
   candidat soit validé ; ne jamais réutiliser l'ancien PFX pour une nouvelle
   release après la bascule.

### Révocation du certificat

1. Suspendre les releases et retirer immédiatement le PFX, son mot de passe et
   son empreinte des secrets CI.
2. Demander la révocation au fournisseur, renouveler les accès CI touchés et
   inventorier tous les artefacts signés depuis la date possible de
   compromission.
3. Retirer les artefacts suspects des canaux sans effacer les preuves, publier
   un avis d'incident et obtenir un nouveau certificat sur un poste propre.
4. Reconstruire depuis un commit audité, avec un nouvel horodatage, puis refaire
   les vérifications Authenticode, minisign et Smart App Control. Ne pas
   présumer du statut des anciennes signatures horodatées : conserver ou
   retirer chaque version selon le verdict du fournisseur et de Windows.

## Preuves minimales à conserver

- motif (`planifiée`, `expiration`, `perte`, `compromission`) et fenêtre UTC ;
- opérateur et relecteur ;
- versions source, version-pont et première version sous la nouvelle clé ;
- empreintes publiques avant/après ;
- identifiants des runs CI et commit source ;
- résultats des tests acceptée/refusée, `signtool` le cas échéant, hashes et
  provenance ;
- décision de fermeture, sort de l'ancienne clé et action de communication.

Références : `docs/DESKTOP_P10_PACKAGING.md`, DEC-0129,
`desktop/scripts/windows-signing.mjs`, `.github/workflows/desktop-release.yml`,
[Tauri Updater](https://v2.tauri.app/plugin/updater/),
[Smart App Control](https://learn.microsoft.com/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
et [SignTool](https://learn.microsoft.com/windows-hardware/drivers/devtest/signtool).
