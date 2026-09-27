# C2 — E2E nouvel utilisateur (inscription → premier usage)

Tâche Studio OS `2295a9ad`, roadmap « Desktop Distribution, Updates & Public
Registration », étape C2. Les deux parcours tournent contre une vraie API
jetable (`desktop/e2e/gate_stack.py` : base PostgreSQL temporaire, admin
aléatoire, inscriptions ouvertes, emails écrits en `.eml`), détruite à la fin.
Aucun résultat d'exécution ici (voir le journal AI work de la tâche).

| Parcours | Test | Étapes vérifiées |
|---|---|---|
| Web | `dashboard/e2e/c2-new-user-live.spec.ts` via `dashboard/scripts/c2-new-user-live.mjs` | inscription par l'écran → lien lu dans le `.eml` → vérification → connexion → « En attente d'accès » (rôle `readonly`) → attribution par l'admin → tableau de bord du seul projet attribué → premier usage : la tâche du projet est listée, rien de l'autre projet ; ni secret, ni mot de passe, ni JWT dans le stockage, l'URL ou la console ; zéro erreur page/CSP |
| Desktop | `desktop/scripts/a5-enroll-e2e.mjs` (contrôles `c2.*`) | exécutable release réel + sidecar + trousseau OS : inscription → assistant « Connexion » → « Enregistrer ce poste » sans admin → attente d'accès → attribution → projet choisi dans l'assistant (étape « Dossier » atteinte) → premier usage de la machine : tâche du projet listée, aucune tâche de l'autre projet ; aucun secret dans le profil ; entrée du trousseau supprimée |

L'étape « Dossier » ouvre le sélecteur natif de l'OS : sa traversée réelle est
couverte par `desktop/scripts/onboarding-walkthrough.mjs` (pas automatisable
sans humain ou agent computer-use).

Commandes (PostgreSQL avec droit `CREATEDB`) :

```powershell
$env:STUDIO_GATE_PG_ADMIN_URL = "postgresql://studio:studio@127.0.0.1:5432/postgres"
cd dashboard; node scripts/c2-new-user-live.mjs
cd desktop; $env:STUDIO_DESKTOP_ALLOW_INSECURE_ORIGIN = "1"
node scripts/build.mjs --api-url http://127.0.0.1:8765 --sidecar
node scripts/a5-enroll-e2e.mjs   # résultats : desktop/.build/a5-enroll-results.json
```

Sans `STUDIO_C2_LIVE`, la spec Web est ignorée par `npm run test:e2e`.
