# P1.6 — métriques (validation partielle)

Trois essais E04 OpenCode spontanés ont été exécutés après correction sur tâches distinctes de la fixture locale. Ces mesures décrivent uniquement ce petit échantillon.

| Mesure | P1.5 baseline | P1.6 après correction |
|---|---:|---:|
| Tentatives `studio_start_work` en readonly OpenCode | 2 observées | 2/3 essais |
| Acks sur session fermée | observés dans les 3 harnais | non mesuré |
| Sessions créées par audit readonly | observées dans fixture | 2 au total, une par échec |
| Événements métier | non comparable | 2 par échec; 0 au succès |
| Appels MCP totaux | non comparable | 3, 16 et 10 appels d’outils, respectivement |
| Durée | partielle | 36,4 s; 150,5 s (timeout); 90,1 s |
| Coût déclaré par OpenCode | indisponible | environ 0,006; 0,020; 0,016 USD |
| Tokens | indisponible | non présents de façon exploitable dans ces traces |

Les coûts sont la somme des champs `step_finish.cost` du journal natif et ne sont pas une mesure de facturation indépendante. Voir `validation-p1-e2e/E2E-METRICS.md` pour les limites historiques. Aucun gain de comportement ou de coût n’est revendiqué.
