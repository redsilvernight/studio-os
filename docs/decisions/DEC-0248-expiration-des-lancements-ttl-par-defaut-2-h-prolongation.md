---
id: DEC-0248
title: 'Expiration des lancements : TTL par défaut 2 h, prolongation par activité
  et arrêt propre côté serveur'
status: accepted
date: '2026-10-27'
supersedes: []
superseded_by: []
source: server-export
---

# DEC-0248 — Expiration des lancements : TTL par défaut 2 h, prolongation par activité et arrêt propre côté serveur

AMEND DEC-0173 (expiration serveur des TaskLaunch). Statut proposé.

Constat (tâche 63a909ea, NEXUS launch 7b29930a) : un TTL de 15 min tuait un agent en plein travail (`expired_timeout`) sans handoff, en laissant une session active et un claim tenu.

1. `LAUNCH_DEFAULT_TTL_SECONDS` passe de 900 à 7200 s (2 h). Bornes inchangées (60..86400), client N-1 inchangé : seul le défaut du champ optionnel `expires_in_seconds` bouge.
2. Prolongation par activité : un lancement non terminal périmé dont la session de travail liée est encore ouverte et dont la dernière activité est < `STUDIO_LAUNCH_ACTIVITY_GRACE_SECONDS` (défaut 900 s) voit `expires_at` repoussé de cette fenêtre, sans changer `version` ni émettre d'événement ; plafond dur `created_at + 86400 s`.
3. Le report/cancel qui tient déjà la ligne sous `with_for_update` ne commite pas la prolongation : son propre commit la persiste et `expected_version` reste valide (pas de 409 auto-infligé). Les lectures (GET/list/pull) et le sweep la persistent quand la prolongation survient.
4. Arrêt propre à l'expiration réelle : fermeture de la session liée (`session.ended`, `reason=launch_expired`, acteur system, `machine_id` = machine cible, event_id dérivé) et libération des claims de la tâche tenus par la machine cible (`resource.released`, acteur system, `machine_id` = machine cible, event_id déterministe par claim), le tout dans la même transaction que `task_launch.expired`.
5. Contrats mis à jour dans le même changement : TECH/02 (expiration et arrêt propre), TECH/03 (acteur system et attribution machine sur resource.released/session.ended), TECH/04 (fermeture serveur de session) ; openapi.json et openapi-schema.ts régénérés (défaut 7200).
6. Dashboard : choix explicite du délai dans le panneau de lancement (30 min à 24 h), défaut 2 h, plus de 900 codé en dur ; le lancement par lot de roadmap utilise le défaut de 2 h.

Hors périmètre : le timeout local du daemon (`launch_timeout_seconds`, 1 h) reste indépendant du TTL serveur et n'est pas modifié ici.
