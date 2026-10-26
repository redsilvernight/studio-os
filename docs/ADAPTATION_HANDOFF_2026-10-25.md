# Passation — arrêt demandé le 25 octobre 2026

## Reprendre ici

Arrêt explicite demandé par l’utilisateur. Ne pas poursuivre automatiquement. Le travail est local, non intégré, non déployé. Branche `codex/adapt-library-foundations`, HEAD `4f53b6e4`, base `0a7e14f0`. Les douze commits locaux depuis la base couvrent skills utilisateur, roadmaps draft, diagnostic Git, identité durable, découverte, composition explicite, coordination, preuves d’exécution, packs, contexte/MCP bornés et restauration des projections. `git log` donne les références exactes.

Brief original : `C:/Users/redsi/.codex/attachments/94b0f68a-ebef-4f8f-aa36-5b24ac9bbd11/Texte collé.txt`. Projet Studio OS `2a836038-153c-41cf-879a-73bd794760b0`, cadrage `71cc41ed-4b61-4383-be85-c0cb0fe345b2`, roadmap draft `771d8995-406d-4f9a-bae2-1bb9d5e1a5d6` (non approuvée/activée). État et handoffs détaillés dans Studio OS ; démarrer par le protocole et `studio_start_work`.

## Lot en cours, volontairement non committé

Tâche `c68fb57b-cc19-40fa-acb4-c5c013ff6a89`, version 2 au checkpoint, session `c9a330a4-8441-42b1-80d2-6d209bd2ead1`. Agent `8250c5f0-0efa-4958-99c4-d8f74753b60a`, machine `6928f2eb-af43-425b-abad-740bc6338c2d`. DEC-0243 proposée `bcd39613-1b47-4518-9bd0-65ae73646529`, pas acceptée.

- Nouveau contrat `completion.py` : preuve déclarative `studio.completion/v1`, types code/audit/diagnostic/operation, artefacts, validations et constats distincts, codes de sortie stricts ; Git/révision requis pour code, effets vérifiés pour opération, intégration/CI selon exigences explicites. Aucun défaut de branche.
- Handoff API/MCP : preuve optionnelle, cohérence contrôlée avant mutations ; refus de clôture incohérente, persistance dans AI work via agent + summary. Réponse legacy inchangée, hash d’idempotence legacy conservé quand preuve absente. Le MCP actuellement déployé ne connaît PAS ce nouveau paramètre : ne pas lui transmettre `completion`.
- SDK handoff ajouté, CLI offline `completion check` avec lecture bornée.
- Préparation worktree : plus de défaut `dev`, choix origin/HEAD puis branche courante puis HEAD ; timeout Git 30 secondes explicite.
- Sources canoniques `.agents/rules/studio-protocol.md`, `.agents/skills/studio-task/SKILL.md`, `.agents/skills/studio-handoff/SKILL.md` ajustées aux preuves par type. Vérification adapters : 26 entrées, zéro échec, pas de différences de projections générées. Ne pas modifier leurs projections manuellement.
- Tests ajoutés : contrats, API handoff, CLI completion, SDK, MCP idempotence et bases Git main/trunk/release/remote HEAD/timeout.

Validation confirmée : 36 tests ciblés contrats/API completion/préparation/protocole passés ; mypy 380 fichiers passé avant les derniers ajustements de tests. Un dernier lot API/MCP/SDK/CLI (ancienne session exec 55248) et un contrôle statique ont été lancés mais leurs sorties finales n’ont pas été récupérées : résultat NON confirmé, à relancer au besoin. Cette session exec n’existe plus. Ne pas affirmer ce lot vert.

Prochaines actions : relire le diff ciblé ; compléter TECH/02 et TECH/07 pour preuve optionnelle, limites et erreurs ; régénérer OpenAPI depuis la vraie API locale ; tests ciblés + ruff/mypy/build ; commit explicite des seuls chemins de ce lot ; Graphify exact changed paths ; handoff. Garder la tâche en cours tant que les critères globaux ne sont pas établis.

## Protéger absolument

Changements préexistants de l’utilisateur : `.codex/config.toml`, `opencode.json`, `dashboard/test-results-retours-roadmap/`. Ne pas éditer, ajouter à un commit, nettoyer ou restaurer ces chemins. Le test `test_shared_repository_config_is_clean` échoue à cause des chemins personnels conservés dans `.codex/config.toml` ; ce n’est pas une validation verte. Le lot adjacent a donné 49 passés, 1 désélectionné.

Aucune publication/déploiement, push/merge, modification de bibliothèque de production, suppression de transfert/stockage ou configuration personnelle autorisée par ce chantier local. Une tentative antérieure de liaison API directe roadmap/tasks a été refusée par auto-review : ne pas contourner ; références/dépendances sont stockées dans les métadonnées/descriptions. Utiliser des chemins explicites pour `git add` (ajout dynamique précédemment refusé).

## Machine et validation

Bonsai doit rester ARRÊTÉ, Docker aussi. Un démarrage automatique Docker lors du préflight a épuisé la mémoire engagée Windows et provoqué les erreurs Git/WhisperFlow signalées. L’utilisateur a arrêté Bonsai et libéré la VRAM. Aucun rechargement/inférence. Le préflight a depuis été corrigé : lecture seule par défaut ; ne pas utiliser `-StartServices`/`-Migrate` ici.

Des services de test natifs avaient été lancés sous `C:/Users/redsi/AppData/Local/Temp/studios-native-tests-65c649b38ee5480db7c03e9c356f4f2d` : PostgreSQL port 55432, base `studio_os_test`, utilisateur studio (trust), migration 0038 ; MinIO port 19000, bucket studio-transfers. À l’arrêt, inventaire sandbox `Get-Process` sans résultat exploitable et CIM refusé : état actuel NON confirmé. Ne pas supposer ces services démarrés ; vérifier sans relancer Docker. Ne pas tuer de processus par nom.

Env de tests : `STUDIO_TEST_DATABASE_URL=postgresql+asyncpg://studio@127.0.0.1:55432/studio_os_test`, `STUDIO_S3_ENDPOINT_URL=http://127.0.0.1:19000`. Exécuter PowerShell, préflight lecture seule, puis `.venv/Scripts/python.exe -m pytest <cibles> --require-infra -q -x --tb=short`. Aucun full suite, CI ou merge vérifié. Ne pas lancer une grosse suite au simple redémarrage.

## Suite du chantier après le lot courant

1. Défaut identifié dans les profils de lancement : `profile_digest` ne tient pas compte des UUID (kind/key/version/origin uniquement), collision possible studio/utilisateur de même clé/version. Points d’appel `services/api/services/task_launches.py` et client `daemon/runtime.py`. Concevoir compatibilité N/N-1 et version de contrat avant correction ; ne pas casser les profils legacy.
2. Git onboarding reste diagnostic + guide manuel : installation/configuration/initialisation guidées avec consentements produit et re-vérification restent à terminer.
3. Identités : rapprochement legacy et transitions de modèle/session, matrice des points d’entrée restent à vérifier.
4. Même home OS avec changement de compte : pas encore résolu pour projections. Absence dans fetch borné ne prouve pas suppression ; ne pas purger automatiquement.
5. Journal projections : succès skills puis échec definitions peut laisser un journal skills marqué appliqué après rollback mémoire global ; hashguard empêche écrasement mais inventaire imparfait. Restauration locale ne modifie pas les pins serveur ; autosync peut réappliquer.
6. Préflight worker spécifique au projet, preuves OpenCode, validation vault/DEC et scénarios intégrés restent à compléter. Outils personnels Bonsai/OpenCode : inspecter interfaces seulement, aucune extension silencieuse du périmètre.
7. Revue contrats avant intégration ; full suite une fois juste avant merge, dans un contexte adapté aux changements personnels préservés.

## Graphify

Launcher exclusif `scripts/graphify-studio.ps1`, graphe central `E:/Graphify/Studio-OS/graphify-out`. Mise à jour AST confirmée jusqu’au commit HEAD `4f53b6e4` : 19551 nœuds, 57904 liens, 800 communautés, coût d’inférence 0 token / 0 $. Trois anciens nœuds curatés sans source_file et labels de communautés devenus approximatifs restent signalés ; ne pas lancer `graphify label` ni Bonsai. Le lot non committé n’a pas encore été indexé. Mettre à jour ses chemins exacts après reprise/validation, sans extraction sémantique.
