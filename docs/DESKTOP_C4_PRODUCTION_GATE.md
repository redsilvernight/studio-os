# C4 — Gate de production publique et runbook incident

Le serveur Flo-laptop doit d’abord être mis à niveau avec le déploiement local
one-shot décrit dans [FLO_LAPTOP_DEPLOYMENT.md](FLO_LAPTOP_DEPLOYMENT.md). Cette
opération ne promeut aucun artefact Desktop.

Ce gate clôt la roadmap « Desktop Distribution, Updates & Public Registration ».
Il ne remplace pas les tests C2 : il prouve le même parcours contre une instance
réellement exposée et un canal de mise à jour réellement publié. Les résultats
d'exécution vivent dans le journal AI work Studio OS, jamais dans ce document.

## Conditions d'entrée

L'ouverture générale des inscriptions est interdite tant que les conditions
suivantes ne sont pas toutes vraies :

- les étapes A0, A1, A3, A4 et C2 sont terminées dans la roadmap active ;
- l'instance exposée répond à `/healthz` et publie les routes d'inscription dans
  `/openapi.json` ;
- `desktop-dev/latest.json` vise cette instance, et non `127.0.0.1` ;
- une release immuable N-1 existe avant tout exercice de rollback ;
- l'opérateur et le relecteur sont identifiés pour les gestes qui modifient une
  inscription, un compte, une machine ou un canal de release ;
- le compte, la machine et le projet utilisés par l'exercice sont jetables.

Authenticode reste hors de ce gate tant que DEC-0129 n'est pas remplacée. La
signature minisign de l'updater reste obligatoire pour démontrer N-1 vers N.

## Préflight automatisé, sans mutation

Depuis `desktop/` :

```powershell
node scripts/production-gate.mjs `
  --base-url https://studio.example.test `
  --expected-api-origin https://studio.example.test `
  --registration closed `
  --require-stable
```

Le programme vérifie la santé, le contrat OpenAPI, l'état du gate
d'inscription et les releases GitHub. Il refuse notamment une origine API
différente, un installeur dont taille ou SHA-256 divergent du manifeste, une
signature updater absente et un canal stable manquant. Sa sortie JSON peut être
jointe telle quelle au journal AI work ; elle ne contient aucun secret.

Le mode `--registration closed` utilise seulement une adresse volontairement
invalide. Il ne crée ni compte ni e-mail. Utiliser `open` uniquement pendant la
fenêtre contrôlée décrite ci-dessous.

Avant de reconstruire le canal Dev, vérifier les deux environnements :

```powershell
gh variable list --env desktop-dev
gh variable list --env desktop-prod
```

`STUDIO_DESKTOP_API_URL` doit être l'origine exposée identique dans les deux
environnements. Une modification avec `gh variable set ... --env ...` affecte
les prochains binaires publiés : elle exige une confirmation explicite pour la
fenêtre courante, puis un nouveau run `Desktop channels`.

## Preuve du cycle complet

Chaque ligne produit une preuve datée : URL publique, identifiant de run, tag,
version, SHA-256 public, capture ou résultat JSON. Aucun mot de passe, JWT, token
machine, lien de vérification ou clé privée ne doit être conservé.

1. **Découverte.** Depuis un poste sans configuration Studi'OS, ouvrir le
   dashboard exposé et la release `desktop-dev`. Exécuter le préflight en mode
   `closed` et conserver le résultat.
2. **Ouverture contrôlée.** Sur l'hôte, définir
   `STUDIO_PUBLIC_REGISTRATION_ENABLED=true` dans `docker/.env`, puis appliquer
   uniquement la configuration nécessaire avec `docker compose up -d api`.
   Exécuter le préflight en mode `open`. Ne pas annoncer cette fenêtre ; la
   refermer dès que le compte jetable a été vérifié.
3. **Inscription.** Créer le compte jetable par l'écran public, consommer son
   lien à usage unique, choisir son mot de passe, puis constater le rôle
   `readonly` et l'absence de projet. L'administrateur lui attribue seulement le
   projet jetable.
4. **Premier usage.** Installer la release N-1 du canal Dev, enrôler une machine
   jetable, sélectionner le projet et lire une tâche de ce projet. Vérifier
   qu'un autre projet reste invisible.
5. **Update.** Publier N sur `desktop-dev`, lancer la recherche de mise à jour
   dans Paramètres › Application, installer et laisser l'application redémarrer.
   Appliquer les contrôles N-1 vers N de `docs/DESKTOP_C2_E2E.md` : version,
   identité machine, workspaces, `shell-settings.json`, outbox SQLite, heartbeat
   et absence de réenrôlement.
6. **Reprise.** Couper le réseau, créer une mutation rejouable dans le projet
   jetable, redémarrer le Desktop, rétablir le réseau et constater un seul rejeu.
7. **Fermeture.** Remettre
   `STUDIO_PUBLIC_REGISTRATION_ENABLED=false`, exécuter
   `docker compose up -d api`, puis le préflight en mode `closed`. Supprimer ou
   désactiver les identités jetables selon la politique de conservation.

## Runbook incident

### Fermer les inscriptions

1. Définir `STUDIO_PUBLIC_REGISTRATION_ENABLED=false` dans `docker/.env`.
2. Exécuter `docker compose up -d api` depuis `docker/`.
3. Exécuter le préflight avec `--registration closed`.
4. Vérifier qu'une connexion existante et la récupération de mot de passe
   restent disponibles. La fermeture n'est pas une révocation de comptes.

La réouverture reprend la même procédure avec `true`, après résolution et
validation à deux personnes.

### Révoquer sans élargir l'impact

Pour invalider les sessions d'un compte :

```powershell
docker compose run --rm api python -m studio_api.admin_cli user revoke-sessions --email user@example.test
```

Pour bloquer toutes ses sessions et machines jusqu'à réactivation :

```powershell
docker compose run --rm api python -m studio_api.admin_cli user disable --email user@example.test
docker compose run --rm api python -m studio_api.admin_cli user enable --email user@example.test
```

Pour une machine précise :

```powershell
./revoke-machine.sh <machine_id>
```

Une révocation de credential machine n'est pas annulable : l'exercice utilise
une machine jetable, constate le refus à la requête suivante, puis réenrôle un
nouveau credential. Ne jamais tester ce point sur la machine de production de
l'opérateur.

### Suspendre un canal de mise à jour

Deux personnes valident le geste. Avant toute mutation, télécharger
`latest.json` et l'installeur, relever leurs SHA-256 et conserver les URLs et le
run source. La suspension minimale consiste à retirer uniquement la découverte
de mise à jour, pas l'installeur ni les preuves :

```powershell
gh release download desktop-prod -p latest.json -D .incident-evidence
gh release delete-asset desktop-prod latest.json --yes
```

Vérifier que l'URL de `latest.json` répond 404 tandis que les installations déjà
présentes démarrent encore. Après résolution, remettre **le même fichier** et
vérifier son SHA-256 avant de rouvrir :

```powershell
gh release upload desktop-prod .incident-evidence/latest.json --clobber
```

Ces commandes sont un geste public et destructif temporaire : ne jamais les
exécuter sans confirmation explicite pour l'incident ou l'exercice courant.

### Rollback de release

Le rollback repromeut un artefact immuable déjà conservé ; il ne rebuild jamais.

```powershell
gh workflow run desktop-promote.yml --ref dev `
  -f from=stable -f to=stable -f source_tag=desktop-vX.Y.Z
```

Attendre la conclusion du run, puis exécuter le préflight avec
`--require-stable`. Vérifier que la taille et le SHA-256 du nouvel asset stable
sont ceux de la release source et qu'un client N accepte le retour seulement si
la politique de compatibilité l'autorise.

### Rotation ou compromission des clés

Appliquer `docs/DESKTOP_B4_KEY_RUNBOOK.md`. Une compromission de la clé updater
impose la suspension immédiate des manifests, la révocation des accès au secret
CI, K2 générée sur un poste propre et une réinstallation par canal indépendant :
K1 ne peut pas établir la confiance dans K2. Pour Authenticode, la procédure
reste dormante tant que DEC-0129 est active.

## Exercice et sortie du gate

L'exercice incident doit couvrir, avec des identités et un canal jetables :

1. fermeture puis réouverture des inscriptions ;
2. révocation de session, désactivation/réactivation du compte et révocation
   irréversible d'une machine jetable ;
3. suspension puis restauration d'un manifeste, avec SHA-256 identique ;
4. rollback depuis une release immuable N-1 ;
5. scénario sur table de perte ou compromission de la clé updater, avec noms des
   responsables, canal de communication et critères de réouverture.

Le gate est PASS uniquement si le cycle complet et l'exercice sont consignés
dans `studio_log_ai_work`, que le préflight final passe, que les inscriptions
sont revenues à l'état décidé et qu'aucun compte, machine, fichier temporaire ou
canal jetable ne reste actif. Sinon C4 reste `in_progress` ou `blocked` avec les
écarts exacts ; une simulation locale ne vaut jamais preuve d'instance exposée.
