# Mission Control — vue projet (P02-mission-ui)

Affiche le read model `GET /api/v1/projects/{project_id}/mission`
([read-model.md](read-model.md)) dans l'espace projet. Lecture seule : aucune
action de mutation (lancer, annuler, valider) n'est proposée ici.

## Surfaces

- Onglet **Exécutions** : `#/projects/<id>/mission`, liste paginée complète.
- **Vue d'ensemble** : section résumée (compteurs + 3 runs à regarder au plus,
  verdicts `waiting_human`, `needs_attention`, `stale`, `failed`), lien vers
  l'onglet. Aucun élément majeur ajouté au-delà du budget (≤ 7).
- Module chargé avec la vue projet (chunk différé) : rien dans le chargement
  initial.

## Affichage

- Le verdict serveur est affiché tel quel, jamais re-dérivé. Verdict, raison,
  état de protocole ou lacune inconnus : libellé « inconnu » + code brut, ton
  neutre.
- Raison affichée : `reasons[0]` ; les autres raisons dans le détail.
- Un run = un `<details>` : résumé (verdict, titre de tâche, raison,
  mise à jour) ; ouvert : lancement → session → résultat (résumé du handoff
  ou « Aucun résultat transmis »), lien `#/tasks/<task_id>`. Lancement →
  session → résultat ≤ 2 clics depuis l'onglet.
- Aucun UUID visible hors `dsTechDetails` repliés.
- `data_gaps` : mention explicite « donnée manquante », jamais de valeur
  fabriquée.

## Temps réel et dégradé

- Le flux SSE du shell re-rend la vue (source de vérité inchangée).
- `live()` vaut `live`, `lost` ou `off`. En `lost` : bandeau « Mises à jour en
  direct interrompues », heure de `generated_at`, bouton Actualiser, et
  rafraîchissement automatique borné (30 s, 10 essais) puis arrêt annoncé.
  Arrêt immédiat si la vue est détachée ou si `live()` repasse à `live`.
- 403 : état « Accès refusé » sans détail d'un autre projet. Erreur réseau :
  état d'erreur avec Actualiser.

## Contrat DOM (tests)

| Sélecteur | Rôle |
|---|---|
| `[data-mission]` | racine de l'onglet |
| `[data-mission-summary]` | section de la vue d'ensemble |
| `[data-mission-counts]` | compteurs par verdict (`counts`, toute la fenêtre) |
| `[data-mission-run="<run_id>"]` | un run (`<details>`), attribut `data-verdict` |
| `[data-mission-result]` | bloc résultat d'un run |
| `[data-mission-gap]` | mention de donnée manquante |
| `[data-mission-live="lost"]` | bandeau de perte du direct |
| `[data-mission-refresh]` | bouton Actualiser |
| `[data-mission-more]` | bouton page suivante (`next_cursor`) |
| `[data-mission-denied]` | état accès refusé |
