# Architecture canonique de skills proposée

Audit du 4 novembre 2026. Tous les chemins ci-dessous sont des propositions, pas des créations ou suppressions effectuées. Le catalogue réellement disponible est dans [01](01-MCP-INVENTORY.md).

## Constat

La séparation `.agents/` canonique → projections Claude/Codex/OpenCode est déjà implémentée. Il faut réparer ses propriétaires et ses tests, pas construire un second moteur de génération. Les définitions de bibliothèque serveur constituent un autre canal versionné : préciser l'origine active et éviter qu'un export utilisateur réécrive silencieusement la projection projet.

| Élément actuel | Usage et constat | Cible proposée |
|---|---|---|
| studio-protocol | 11 lignes, amorçage permanent ; cite studio-workflow/next | Garder court ; rendre explicite tâche suivie vs audit lecture seule |
| studio-context | Préparation initiale, refresh et reprise | Référence du skill commun ; alias de compatibilité avant éventuel retrait |
| studio-task | Cycle start/sync/log/handoff | Skill commun principal ; supprimer le log systématique avant handoff |
| studio-handoff | Clôture, preuve selon nature, reprise | Référence du skill commun ; ne pas recopier le cycle complet |
| studio-decision | Proposer, admin-gated accept/supersede | Spécialisé, chargé sur choix durable seulement |
| contract-change | Procédure de changement partagé | Garder ; contract-guardian = revue indépendante, pas doublon à supprimer |
| alembic-migration | Migration réversible et round-trip | Garder, déclencheur schéma/DB |
| openapi-sync | Snapshot/types dashboard après changement API | Garder, déclencheur API exact |
| offline-sync-testing | Checklist replay/claims/transfers | Garder une checklist canonique ; les rôles la référencent |
| graphify | Relations/index code | Garder, à la demande et avec fraîcheur ; pas une étape universelle de chaque sous-agent |

Sources : `.agents/skills/*/SKILL.md` ; recouvrement du cycle aux `studio-task:10-30`, `studio-context:10-18`, `studio-handoff:8-12`. Les six définitions canoniques sont en lecture seule (`.agents/definitions/*.md:1-20`). L'invocation de Graphify est répétée dans `studio-architect.md:33`, `contract-guardian.md:38`, `sync-debugger.md:38`, `studio-tester.md:16` : n'en garder qu'un principe commun conditionnel.

Un recouvrement de sujet n'est pas automatiquement un gaspillage : un skill décrit une procédure exécutable ; un rôle fournit un jugement indépendant. Fusionner les textes de procédure, préserver les responsabilités de revue.

## Source unique et propriétaires

Le générateur projet rend le bloc GENERATED (`packages/studio-client/src/studio_client/canonical.py:552-585`) ; sa mise à jour remplace une occurrence (`cli.py:1549-1562`). Un script utilisateur distinct rend le bloc SYNCED (`C:/Users/redsi/.codex/sync-claude-config.ps1:94-126`). AGENTS contient les deux : 32 605 octets, deux blocs d'environ 15,5 k caractères chacun. Les retirer à la main serait temporaire.

Recommandation : propriétaire unique pour le contenu projet, générateur `studio-client adapters`. Le synchroniseur utilisateur peut gérer ses règles personnelles hors de ce bloc et doit cesser de produire le bloc projet concurrent. La transition doit détecter les marqueurs hérités et migrer de façon contrôlée ; ne jamais supprimer un texte utilisateur hors blocs reconnus.

Le contrôle actuel peut être vert malgré un bloc supplémentaire : `tests/client/test_canonical_p3.py:188-205` vérifie la présence attendue. Ajouter unicité, conservation hors blocs et stabilité après deux générations en répertoire temporaire. Le contrôle exécuté sur ce checkout a détecté six drifts TOML Codex ; ces fichiers étaient déjà modifiés avant audit. Cela ne démontre pas un défaut du moteur de génération.

## Répartition cible

| Niveau | Contenu | Ce qui n'y appartient pas |
|---|---|---|
| Règles globales personnelles | Langue, préférences, autorisations, routage outils poste | État projet, catalogue exhaustif, règles métier du dépôt |
| Protocole projet permanent | Source canonique, entrée sûre, réutilisation contexte, retry, preuve et clôture | Tutoriels longs, tous les contrats, toutes les checklist de tests |
| Skill commun workflow | Branches de démarrage, refresh, sync/ack, conflits, checkpoint, reprise | Six copies du même cycle par rôle |
| Références conditionnelles | Lecture seule, développeur, validation, documentation, coordination | Modèles/harness imposés à tous les environnements |
| Skills spécialisés | Contrats, migration, OpenAPI, replay, décision, relations graph | Synchronisations systématiques sans déclencheur |
| Définitions de rôle | Mission, critères, autorité, sortie et déclencheur de délégation | Procédures recopiées, modèle fournisseur canonique |
| Découverte dynamique | Version de définition/runtime, capacités inconnues, contenu ciblé | Redécouverte de tout à chaque tour |
| Projections harness | Syntaxe, permissions/outils, bindings runtime et modèles locaux | Nouvelle politique métier divergente |

## Structure proposée

```text
.agents/
  rules/studio-protocol.md
  rules/{contracts,database,mcp-tools,offline-sync,python-conventions,storage-transfers,testing}.md
  skills/studio-workflow/
    SKILL.md
    references/{context,checkpoint,handoff,read-only,validation}.md
  skills/{studio-decision,contract-change,alembic-migration,openapi-sync,offline-sync-testing,graphify}/
  definitions/{studio-architect,contract-guardian,sync-debugger,studio-tester,migration-reviewer,dashboard-a11y}.md
```

`studio-workflow` est un nom cible proposé. Le protocole le cite déjà, mais le catalogue local de neuf skills ne contient pas ce répertoire : vérifier les définitions serveur avant de conclure à son absence globale. Préférer une évolution du skill existant `studio-task` si elle évite de changer les déclencheurs et références externes. Garder des alias courts `studio-context`/`studio-handoff` pendant la migration ; aucune suppression immédiate.

Les six profils métier de la demande peuvent être des paragraphes de spécialisation et des références légères. Ils ne justifient pas six skills chargés d'office ni six sous-agents obligatoires.

## Exemples de contenu — non appliqués

### Protocole permanent

```markdown
# Studio Protocol
État partagé : Studio OS ; contexte LLM : cache temporaire.
Travail suivi autorisé : start_work une fois ; réutiliser contexte et sync reçus.
Audit imposé en lecture seule : prepare_context ; aucune mutation de suivi.
Charger studio-workflow seulement pour exécuter ou reprendre le cycle.
Lire why/omissions ; chercher seulement le contenu nécessaire.
Claims = avertissements TTL ; sync aux frontières et ack après traitement.
Retry : même clé/payload ; 409 : relire, fusionner et réessayer.
Décision durable : proposer ; résoudre uniquement avec le rôle requis.
Clôture : preuves adaptées au travail, puis handoff si session autorisée.
Ne pas confondre implémenté, testé, intégré et déployé.
```

### Skill commun

```markdown
---
name: studio-workflow
description: Démarrer, synchroniser, transmettre et reprendre un travail Studi'OS autorisé.
---
1. Identifier le mode : suivi ou observation lecture seule.
2. start_work si tâche suivie ; prepare_context pour observation/refresh.
3. Conserver IDs, version, clé, next_cursor et omissions. Ne pas relire ce qui est reçu.
4. Références ciblées ; claims groupés seulement pour les chemins utiles.
5. Traiter sync puis ack ; coordinate seulement si une autre session doit adapter son plan.
6. Valider selon la nature et le risque ; conserver commande, exit et artefacts.
7. Handoff avec preuve et NEXT si session autorisée ; sinon restituer les artefacts.
Erreurs et limites : references/checkpoint.md et references/handoff.md.
```

La correction de livraison du handoff doit précéder une promesse d'ack fiable dans ce texte. Il ne faut pas résoudre un défaut serveur par une instruction faussement rassurante.

### Spécialisation auditeur

```markdown
Mode lecture seule imposé : aucun start_work avec tâche, claim, décision ou handoff.
Comparer documentation, implémentation, exposition et tests.
Confirmé/probable/hypothèse ; test présent distinct de test exécuté.
Valider les artefacts et les références ; nommer les contrôles non exécutés.
Ne proposer aucune primitive déjà correctement implémentée.
```

### Spécialisation validation

```markdown
Entrée : objectif, diff borné, critères, commande et environnement.
Vérifier indépendamment ; résultat = verdict, preuves, limites, prochaines actions.
Ne pas fermer la session du producteur. completion est une déclaration de cohérence.
```

## Adaptation par harnais

- **Claude Code** : règles à portée `paths`, hooks existants, permissions des rôles et références de skill. Les hooks `.claude/settings.json` sont versionnés mais hors projection gérée ; DEC-0209 et `scripts/claude-hooks/` doivent rester la source de leur comportement.
- **Codex** : TOML de rôles, bindings de modèles/outils propres au harnais ; AGENTS amorçage court. Une règle à paths ne doit pas être entièrement inlinée de façon permanente pour simuler un chargement conditionnel.
- **OpenCode** : adapter la syntaxe agents/config et bindings, préserver la politique commune. Un job d'exécution automatique avec commit n'est pas adapté à une mission qui interdit tout commit ; ne pas l'invoquer par simple préférence globale de délégation.

Les différences de capacité doivent être explicites, sans promettre que Codex reproduit les hooks Claude. Le modèle d'agent reste un choix de projection/runtime, pas une contrainte de mission canonique.

## Critères d'acceptation d'une migration future

Un seul propriétaire par bloc ; aucune perte de contenu utilisateur ; aucun doublon ; génération deux fois identique ; check des trois adapters ; triggers des anciens noms encore résolus ou migration annoncée ; 63 outils et droits existants conservés hors retrait versionné ; tests des exceptions lecture seule et de reprise zéro historique. Pas d'optimisation de tokens annoncée sans mesure de sessions comparable.
