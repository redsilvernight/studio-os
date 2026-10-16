# P06 — échantillon pilote et décision sur l'historique

Tâche `db685418-bfd4-4d2e-85d2-2a0867b2e1e7`. Relevé descriptif du
16 octobre 2026, branche issue de `dev` `71da001a`.
**No-go provisoire sur l'historique validé humainement le 16 octobre 2026 (DEC-0219).**

## Périmètre et dénominateurs

Fenêtre AIWork : [2026-10-10T00:00:00+00:00, 2026-10-16T21:31:17+00:00), selon `started_at`.
Source : MCP du serveur connecté `https://studio.flosrent.fr/mcp`.
Export plafonné aux 200 dernières entrées ;
107 autres entrées signalées par le serveur ne sont pas exportées.
La plus ancienne date de début exportée est 2026-09-28T18:35:35.462138+00:00.
Le sous-échantillon de la fenêtre comporte 56 entrées,
55 sessions distinctes et 12 agents.
Il ne constitue pas un recensement certifié de toute la fenêtre. Aucune extrapolation.
La borne de fin est celle de mise en forme du relevé, pas une transaction commune aux sources.

L'export ne contient que des métadonnées (identifiants, liens, statuts, dates), aucun
contenu de conversation ni credential. Un AIWork est une entrée de journal, pas un run.
Les statuts observés sont `{"approved": 8, "completed": 48}`.
1 sessions comportent plusieurs entrées :
on ne transforme jamais leur nombre en nombre de processus exécutés.

## Comparaison descriptive à P01

| Mesure | P01 | Relevé P06 | Portée |
|---|---|---|---|
| Tâche liée | 193/200 (96,5 %) | 56/56 (100.00 %) | Entrées AIWork exportées |
| Session liée | 110/200 (55 %) | 56/56 (100.00 %) | Un lien ne prouve pas un handoff |
| Durée positive (`completed`) | 10/192 (5,2 %) | 1/48 (2.08 %) | Pas du temps actif |
| Durée nulle (`completed`) | 182/192 (94,8 %) | 47/48 (97.92 %) | Pas de durée utile |
| Durée positive TaskLaunch | Seuil ≥90 % (DEC-0195) | Inconnu | Aucun dénominateur de runs mesurables |
| Tokens par harness | Seuil ≥95 % (DEC-0195) | Inconnu | Attribution runtime absente |
| Protocole | Session + handoff (DEC-0201) | Inconnu | Aucun succès déduit de completed |
| Bruit événements/AIWork | 2,0 ; seuil ≤1,1 | Non mesuré | Pas de comptage sur la fenêtre |
| UX humaine | ≥90 % bonnes réponses en ≤5 s | Non réalisé | Aucun succès déduit de l'API |
| Collisions réelles | Pas de baseline pilote chiffrée | Non mesuré | Pas de preuve deux machines |
| Taille/latence start_work et JS initial | P01/DEC-0195 | Non remesurés | Un scénario seedé ne mesure pas la prod |

Les fenêtres et populations P01/P06 diffèrent. Ces différences descriptives ne
prouvent aucune causalité ni performance relative d'un modèle ou harness.

## Sources accessibles et données manquantes

- `studio_list_task_launches(project_id, limit=100, offset=0)` :
  0 lancement retourné pour le projet, toutes dates.
- La projection MCP refuse `harness`, `provider`, `model`, `agent_profile` :
  `unknown fields: agent_profile, harness, model, provider`. Configuration/version par observation : inconnues.
- Contrôle HTTP authentifié `GET /api/v1/projects` : 200. Aux mêmes origine et
  credentials, `GET /api/v1/usage/summary` et `GET /api/v1/projects/{id}/mission` : 404.
  Les paramètres et l'heure sont archivés dans le JSON. La cause du 404 n'est pas établie.
- Tokens, coût, taux de protocole conforme et couverture par configuration : inconnus.
  Un zéro de lancement observé n'est ni un coût nul ni un taux de conformité de 100 %.

## Preuves archivées, hors population de production

[p03-gate.md](p03-gate.md) rapproche trois sorties CLI réelles du 13 octobre :
103 855 tokens, 0,46928960 USD annoncés par le runtime, 30,902 s murales.
Leur ingestion et leurs réservations sont rejouées dans PostgreSQL de test.
Ces trois observations ne sont pas ajoutées au dénominateur de production.
Le transcript stream du second run n'est pas une observation supplémentaire.
La démo locale citée dans ce document porte sur un projet jetable et quatre
lancements, dont une annulation sans mesure ; elle reste également séparée.

## Décision et proposition de reprise

Différer `P06-history-option` tant que les dénominateurs de runs réels et leur
attribution ne sont pas disponibles : no-go provisoire confirmé par l'utilisateur
le 16 octobre 2026 et enregistré dans DEC-0219. La méthode de reprise ci-dessous
reste une proposition ; la validation ne fixe ni calendrier ni minimum.
L'activation de l'historique et la clôture des gates techniques restent suspendues.

Proposition de collecte suivante : sept jours complets après disponibilité des
routes et champs requis, fenêtre exacte publiée à l'ouverture. Collecter tous les
runs de la fenêtre ; publier par configuration le nombre total, les versions,
les liens TaskLaunch/session/handoff, les compteurs mesurés, les absences,
annulations et collisions. Prévoir des observations UX humaines chronométrées
et le pilote deux machines avant de conclure sur ces deux dimensions.
Le minimum par configuration reste à fixer humainement : aucun minimum arbitraire
n'est présenté comme une gate approuvée. Si les effectifs restent insuffisants,
prolonger la fenêtre avec accord humain et publier les nouvelles bornes.

## Reproduction et audit

```powershell
python -m scripts.pilot_sample --check
python -m scripts.pilot_sample --write-report
```

`pilot-sample.json` archive les métadonnées sources et les résultats calculés.
`--check` recalcule les effectifs, refuse doublons, dates naïves, durées négatives
et observations hors fenêtre, puis compare exactement les agrégats et ce rapport.
Il ne contacte aucun serveur et ne nécessite aucune base de données.
Les observations de contrôle sont listées dans `audit` avec leur relecture MCP.
Le snapshot reflète les réponses à la collecte ; une évolution ultérieure des
sources ne modifie pas les résultats archivés.

Références : [metrics.md](metrics.md), [baseline.md](baseline.md),
[read-model.md](read-model.md), [p03-gate.md](p03-gate.md), DEC-0195 et DEC-0201.
