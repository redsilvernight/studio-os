# Préparation de la distribution publique

Point de préparation documentaire du 29 octobre 2026. Ce document rassemble les
conditions de passage à la dernière roadmap ; il ne déclare ni déploiement validé
ni ouverture publique autorisée. La révision de départ du nettoyage est
`58fa3f78` sur `dev`, version produit `0.9.1`.

## Sources de référence

- [Index documentaire unique](../00_README.md).
- [Release serveur](../../../../RELEASE.md) et [versions](../../../VERSION_SCOPE.md).
- [Gate public Desktop](../../../DESKTOP_C4_PRODUCTION_GATE.md).
- [Runbook des clés](../../../DESKTOP_B4_KEY_RUNBOOK.md).
- [Exploitation et sauvegardes](../HUMAN/04_DEPLOIEMENT_OVH.md).
- [Preuves d'exploitation antérieures](../../../mission-control/ops-evidence.md).

Les contrats et décisions acceptées priment. Les résultats historiques doivent
être reliés à leur révision ; ils ne remplacent pas une vérification du candidat.

## Vérifications avant promotion

1. Isoler les modifications à livrer, relire le diff et identifier la révision.
   Le nettoyage a commencé avec des changements locaux de configuration agents
   et `AGENTS.md` ; ils ne doivent pas être inclus implicitement dans une release.
2. Vérifier la fraîcheur de `dev` avec le [préflight](../../../DEV_PREFLIGHT.md),
   puis les contrôles CI de cette révision. Ne pas valider une ref distante à
   partir du seul cache Git local.
3. Exécuter `pwsh scripts/test-env.ps1` avant les tests d'intégration ; lancer les
   tests ciblés puis la suite complète une seule fois avant fusion selon les
   règles du dépôt. Ne pas confondre services indisponibles et tests réussis.
4. Vérifier lint, format, types, export des décisions et projections des agents ;
   construire le Dashboard et contrôler son budget et ses tests navigateur.
5. Depuis `desktop/`, vérifier les versions, notes, licences embarquées,
   packaging et parcours installation/mise à jour avec les gates dédiés.
6. Relire migrations et compatibilité client/serveur. Une restauration du code
   ne restaure pas automatiquement une base migrée.
7. Préparer les notes de version et obtenir l'accord de publication au point
   prévu par `RELEASE.md` ; vérifier les effets réels après déploiement.

## Points à solder ou confirmer dans la dernière roadmap

| Sujet | État connu à l'ouverture de cette session | Preuve attendue |
|---|---|---|
| Restauration périodique et copie hors site | Tâche `8592d0fd-a1f6-48ae-bce7-f8b6407c1740` à faire ; anciennes preuves isolées insuffisantes | Exécution datée sur l'hôte cible, restauration isolée et contrôle de rétention |
| Incidents Desktop avant inscription générale | DEC-0141 a reporté suspension/restauration du manifeste, rollback immuable et exercice de compromission updater | Parcours exécutés et journalisés selon le gate C4 |
| Signature Windows | Authenticode dormant dans le runbook, DEC-0129 ; tâches B1 encore bloquées | Choix confirmé du mode de distribution et, si activé, certificat, garde et rotation vérifiés |
| Retrait des outils MCP dépréciés | Tâche `8fd26e5d-18c3-4754-9826-d7092832b79d` : pas avant le 4 novembre 2026 | Migration des usages, versionnement et revue du contrat avant retrait |
| Canal public et inscriptions | Fermés par défaut ; aucun changement réalisé par ce nettoyage | Artefact immuable, manifeste/signature et contrôle du parcours public sur l'instance cible |

Les statuts ci-dessus viennent du contexte Studio OS consulté pour cette session.
Les relire dans Studio OS avant de planifier ou de clôturer une étape.

## Nettoyage documentaire

Le Markdown est la source maintenue. Les quatre anciens manuels compilés
`Studio_OS_Manuel_Humain.{pdf,docx}` et
`Studio_OS_Reference_IA_Technique.{pdf,docx}` sont retirés du dépôt courant.
Les rapports Wave 1/1B/2 et DU0 sont archivés avec leurs preuves ; les contrats,
exports générés de décisions et corpus consommés par les tests sont conservés.

Les dépendances installées, données locales, `.env`, caches de travail et
worktrees ne sont pas des documents superflus à effacer. Leur présence ne doit
pas les faire entrer dans un paquet public ; les exclusions Git et Docker sont
vérifiées séparément du contenu d'une release.

## Preuve de sortie

Contrôles exécutés pendant le nettoyage : versions synchronisées `0.9.1`, notes
de release et export des décisions à jour. Contrôle des liens Markdown locaux :
aucun nouveau lien cassé ni lien cassé dans les fichiers modifiés ; deux liens
préexistants restent dans les exports de DEC-0142 et DEC-0143. Les corriger à la
source serveur puis régénérer l'export, jamais dans les fichiers générés.

La CI `40887570786` est verte pour la révision de départ `58fa3f78` ; elle ne
couvre pas les changements de cette session. Aucun test d'intégration, build
Docker, déploiement ni exercice public n'a été exécuté par ce nettoyage.

Consigner la révision, les fichiers nettoyés, les commandes et résultats réels,
la CI, la cible de promotion et les points non exercés dans le handoff Studio OS.
Une préparation documentaire terminée n'est pas une certification de production.
