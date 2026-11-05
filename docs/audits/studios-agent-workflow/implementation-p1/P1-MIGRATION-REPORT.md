# P1 — migration finale

04/11/2026, Europe/Paris. **Migrations appliquées et validées localement.** Aucun commit, push, merge, déploiement ou changement de production ; P2 non commencé.

## Baseline et sauvegardes

Branche dev, HEAD d5912008bf8847835d454d3af5083a779909754c, index vide, trois worktrees initiaux. Baseline de finalisation : 2 299 fichiers du dépôt empreintés avant édition, état Git intégral et sept cibles sauvegardées dans :

`C:/Users/redsi/Documents/Coding/Projet/Studi'os/.studio-os/backups/p1-finalization-20261104T210011Z-dbc47557/`

`baseline.json` porte les empreintes, branche/index/worktrees et inventaire ; `sync-claude-config.ps1` est la sauvegarde exacte du script externe ; chaque sous-dossier d'agent porte A-current.toml, B-before-fix.toml, B-final.toml et C-HEAD.toml, ainsi que A-C/B-C/A-B.diff. Les sauvegardes ont des chemins uniques, jamais écrasés. Un premier inventaire interrompu à la détection du TOML invalide reste dans un autre dossier p1-finalization ; aucune migration n'avait alors été appliquée. Les rapports P0/P1 précédents, leurs backups et traces sont conservés.

## Synchroniseur personnel

Cible réelle : `C:/Users/redsi/.codex/sync-claude-config.ps1`. L'empreinte initiale correspondait exactement à personal-sync.json. Le patch préparé était applicable. Sa condition générique `.agents` aurait toutefois modifié la responsabilité d'un projet étranger utilisant ce dossier ; le garde final a donc été réconcilié de façon bornée vers `.agents/rules/studio-protocol.md` (marqueur du protocole Studi'OS). Diff exact : personal-sync-final.patch. personal-sync.patch initial est conservé.

Une seule condition est modifiée : les copies projet agents/skills/règles sont sautées pour les projets portant ce protocole. Les deux appels globaux personnels, les fonctions de conversion, permissions, modèles et comportements étrangers ne sont pas modifiés. Vérification binaire : résultat exact de la substitution unique sur la sauvegarde, sans changement des autres octets. AST PowerShell valide. Aucun lancement sur tous les dépôts ni sur le vrai USERPROFILE : les scripts ont été exécutés exclusivement en fixtures isolées.

Deux passages successifs original/candidat dans les fixtures démontrent absence de réinjection et de doublon, conservation des instructions personnelles, sorties globales identiques, stabilité du second passage, comportement étranger identique avec ou sans un dossier .agents sans protocole. 158 assertions, 15 sous-processus réussis, ACL des fichiers suivis dans les fixtures ; détails finalization-sync-proof.ps1/json/log. Le faux USERPROFILE est propre à chaque subprocess ; HOME et CODEX_HOME ne sont pas réaffectés. Le cache AppData produit par PowerShell n'entre pas dans le hash des configurations et cette exclusion est explicite.

## Réconciliation réelle A / B / C des six Codex

A : fichier installé avant migration, sauvegardé. B : sortie du générateur canonique actuel après le correctif syntaxique décrit plus bas. C : version Git de chacun des six chemins au HEAD fixé ci-dessus, vraie base de référence commune. C n'est pas prétendu syntaxiquement valide partout. La comparaison brute A-C et B-C est conservée ; pour le seul contract-guardian invalide, la description est encodée en mémoire pour analyser les champs, sans modifier C.

Propriétaires : missions/règles/skills dans .agents ; sérialisation TOML et paramètres de raisonnement dans l'adapter ; configuration personnelle éventuelle dans les champs propres ou hors blocs. **Aucune personnalisation incompatible ni section d'origine indéterminée n'est trouvée.** Les six A sont reproduits exactement, LF normalisés, par le synchroniseur historique appliqué aux projections Claude du HEAD dans une fixture indépendante. L'erreur de décodage Git d'un premier essai de preuve a été corrigée dans le harnais UTF-8, pas dans les originaux.

Classification de chaque différence, commune aux six fichiers :

- Description doublement quotée : conversion générée obsolète, texte effectif identique à C ; normalisation des guillemets, aucun texte utilisateur perdu.
- model_reasoning_effort absent : omission mécanique du synchroniseur ; paramètre spécifique au harnais restauré aux exigences canoniques et à C. Aucun modèle concret n'était fixé dans A/B/C : héritage du modèle conservé.
- Marqueur claude-code : projection du mauvais harnais ; remplacé par codex. Référence .Codex/rules inexistante issue du remplacement personnel rétablie à la source/projection existante.
- Corps des instructions : A égale C après ces seules substitutions mécaniques et espaces de bord. B-C contient les changements P1 déjà autorisés : cycle commun en observateur, priorité edit_policy, signalement du graphe périmé. Contradictions avec le workflow corrigées, règles de sécurité conservées.
- Autre branche/agent, personnalisation intentionnelle ou conflit indéterminé : aucun écart supplémentaire détecté. Aucun champ model, permissions, tools ou sandbox personnalisé supprimé ; les configurations externes sont inchangées.

| Agent | Reasoning restauré A←C | Base C | Réconciliation |
|---|---|---|---|
| `contract-guardian` | medium | TOML C invalide ; analyse textuelle et description normalisée en mémoire | Aucun conflit restant |
| `dashboard-a11y` | medium | TOML C valide | Aucun conflit restant |
| `migration-reviewer` | medium | TOML C valide | Aucun conflit restant |
| `studio-architect` | high | TOML C valide | Aucun conflit restant |
| `studio-tester` | medium | TOML C valide | Aucun conflit restant |
| `sync-debugger` | medium | TOML C valide | Aucun conflit restant |

Chaque diff commenté est associé à finalization-three-way.json et finalization-<agent>.diff. Les SHA-256 du texte normalisé LF et des octets B-final sont nommés distinctement ; aucune comparaison binaire n'utilise le hash normalisé par erreur.

## Correctif nécessaire du générateur

Le premier contrôle syntaxique a détecté que `_toml_string` retournait une chaîne sans guillemets si elle contenait une apostrophe : la description de contract-guardian était un TOML invalide, déjà dans C et dans le candidat initial. Le correctif minimal utilise json.dumps(value, ensure_ascii=False), dont les échappements sont compatibles avec les chaînes TOML basiques. Aucun contrat API/MCP n'est modifié. Le nouveau test couvre apostrophe, guillemets, antislashs, contrôles, UTF-8, six projections et deux générations complètes des trois harnais.

## Application et conservation

Après comparaison, sauvegardes, tests isolés et revue indépendante, SHA-256 des sept cibles revérifiés, puis garde appliqué et six agents matérialisés par studio-client adapters export --from-canonical. Il ne s'agit pas d'un écrasement aveugle : chaque résultat attendu B a été réconcilié à A/C avant application. Aucun ajout d'exception anti-dérive. Les sept ACL réelles sont identiques avant/après.

Avant mise à jour du rapport final, 2 292 des 2 299 fichiers préexistants sont identiques ; seuls les six TOML et adapter/codex.py changent. P0, canonique P1, AGENTS, hooks, modèles/configs hors cibles restent intacts. P1-FINAL.md est ensuite mis à jour en ajoutant l'état courant avant l'historique initial, sans supprimer cet historique. État et empreintes : finalization-preservation.json ; contrôle final complété dans le rapport de validation.

Fichiers opérationnels modifiés : script personnel externe ; `.codex/agents/{contract-guardian,dashboard-a11y,migration-reviewer,studio-architect,studio-tester,sync-debugger}.toml` ; `packages/studio-client/src/studio_client/adapters/codex.py`. Nouveau test : `tests/protocol/test_p1_codex_migration.py`. Rapports : P1-MIGRATION-REPORT.md, P1-VALIDATION-REPORT.md, section ajoutée à P1-FINAL.md et traces finalization-*.

Revue indépendante : aucune perte ou régression fonctionnelle identifiée ; convention des hashes B corrigée après remarque. Aucun conflit nécessitant une décision humaine ne subsiste pour ces migrations. Essais modèles, chargement CLI effectif et cycle MCP réel restent des niveaux de preuve séparés, décrits dans P1-VALIDATION-REPORT.md.
