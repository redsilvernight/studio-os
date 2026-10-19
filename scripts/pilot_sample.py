"""Recompute a descriptive P06 snapshot from exported metadata, without network or DB access."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def ratio(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": round(100 * numerator / denominator, 2) if denominator else None,
    }


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    start = timestamp(snapshot["window"]["since"])
    end = timestamp(snapshot["window"]["until"])
    if start >= end:
        raise ValueError("window must be nonempty and increasing")
    rows = snapshot["ai_work_export"]["entries"]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate AIWork ids")
    if any(not start <= timestamp(row["started_at"]) < end for row in rows):
        raise ValueError("AIWork outside the declared half-open window")
    completed = [row for row in rows if row["status"] == "completed"]
    positive = zero = missing_end = 0
    for row in completed:
        if row["ended_at"] is None:
            missing_end += 1
            continue
        duration = timestamp(row["ended_at"]) - timestamp(row["started_at"])
        if duration.total_seconds() < 0:
            raise ValueError("negative AIWork duration")
        positive += duration.total_seconds() > 0
        zero += duration.total_seconds() == 0
    sessions = Counter(row["session_id"] for row in rows if row["session_id"])
    return {
        "ai_work_entries": len(rows),
        "by_status": dict(sorted(Counter(row["status"] for row in rows).items())),
        "distinct_agents": len({row["agent_id"] for row in rows if row["agent_id"]}),
        "distinct_sessions": len(sessions),
        "sessions_with_multiple_entries": sum(count > 1 for count in sessions.values()),
        "task_linked": ratio(sum(bool(row["task_id"]) for row in rows), len(rows)),
        "session_linked": ratio(sum(bool(row["session_id"]) for row in rows), len(rows)),
        "completed_positive_duration": ratio(positive, len(completed)),
        "completed_zero_duration": ratio(zero, len(completed)),
        "completed_missing_end": missing_end,
        "project_launches_returned": len(snapshot["launch_export"]["entries"]),
        "tasklaunch_positive_duration_coverage": None,
        "protocol_successes": None,
        "configuration_coverage": None,
        "tokens_coverage": None,
        "cost": None,
    }


def display(metric: dict[str, Any]) -> str:
    if metric["percent"] is None:
        return "inconnu (dénominateur nul)"
    return f"{metric['numerator']}/{metric['denominator']} ({metric['percent']:.2f} %)"


def report(snapshot: dict[str, Any], metrics: dict[str, Any]) -> str:
    window = snapshot["window"]
    export = snapshot["ai_work_export"]
    comparisons = [
        (
            "Tâche liée",
            "193/200 (96,5 %)",
            display(metrics["task_linked"]),
            "Entrées AIWork exportées",
        ),
        (
            "Session liée",
            "110/200 (55 %)",
            display(metrics["session_linked"]),
            "Un lien ne prouve pas un handoff",
        ),
        (
            "Durée positive (`completed`)",
            "10/192 (5,2 %)",
            display(metrics["completed_positive_duration"]),
            "Pas du temps actif",
        ),
        (
            "Durée nulle (`completed`)",
            "182/192 (94,8 %)",
            display(metrics["completed_zero_duration"]),
            "Pas de durée utile",
        ),
        (
            "Durée positive TaskLaunch",
            "Seuil ≥90 % (DEC-0195)",
            "Inconnu",
            "Aucun dénominateur de runs mesurables",
        ),
        ("Tokens par harness", "Seuil ≥95 % (DEC-0195)", "Inconnu", "Attribution runtime absente"),
        (
            "Protocole",
            "Session + handoff (DEC-0201)",
            "Inconnu",
            "Aucun succès déduit de completed",
        ),
        (
            "Bruit événements/AIWork",
            "2,0 ; seuil ≤1,1",
            "Non mesuré",
            "Pas de comptage sur la fenêtre",
        ),
        (
            "UX humaine",
            "≥90 % bonnes réponses en ≤5 s",
            "Non réalisé",
            "Aucun succès déduit de l'API",
        ),
        (
            "Collisions réelles",
            "Pas de baseline pilote chiffrée",
            "Non mesuré",
            "Pas de preuve deux machines",
        ),
        (
            "Taille/latence start_work et JS initial",
            "P01/DEC-0195",
            "Non remesurés",
            "Un scénario seedé ne mesure pas la prod",
        ),
    ]
    table = "\n".join("| " + " | ".join(row) + " |" for row in comparisons)
    return f"""# P06 — échantillon pilote et décision sur l'historique

Tâche `db685418-bfd4-4d2e-85d2-2a0867b2e1e7`. Relevé descriptif du
16 octobre 2026, branche issue de `dev` `71da001a`.
**No-go provisoire du 16 octobre 2026 (DEC-0219) levé le 19 octobre 2026 (DEC-0221).**

## Périmètre et dénominateurs

Fenêtre AIWork : [{window["since"]}, {window["until"]}), selon `started_at`.
Source : MCP du serveur connecté `https://studio.flosrent.fr/mcp`.
Export plafonné aux {export["returned"]} dernières entrées ;
{export["additional_available"]} autres entrées signalées par le serveur ne sont pas exportées.
La plus ancienne date de début exportée est {export["oldest_exported_started_at"]}.
Le sous-échantillon de la fenêtre comporte {metrics["ai_work_entries"]} entrées,
{metrics["distinct_sessions"]} sessions distinctes et {metrics["distinct_agents"]} agents.
Il ne constitue pas un recensement certifié de toute la fenêtre. Aucune extrapolation.
La borne de fin est celle de mise en forme du relevé, pas une transaction commune aux sources.

L'export ne contient que des métadonnées (identifiants, liens, statuts, dates), aucun
contenu de conversation ni credential. Un AIWork est une entrée de journal, pas un run.
Les statuts observés sont `{json.dumps(metrics["by_status"], ensure_ascii=False, sort_keys=True)}`.
{metrics["sessions_with_multiple_entries"]} sessions comportent plusieurs entrées :
on ne transforme jamais leur nombre en nombre de processus exécutés.

## Comparaison descriptive à P01

| Mesure | P01 | Relevé P06 | Portée |
|---|---|---|---|
{table}

Les fenêtres et populations P01/P06 diffèrent. Ces différences descriptives ne
prouvent aucune causalité ni performance relative d'un modèle ou harness.

## Sources accessibles et données manquantes

- `studio_list_task_launches(project_id, limit=100, offset=0)` :
  {metrics["project_launches_returned"]} lancement retourné pour le projet, toutes dates.
- La projection MCP refuse `harness`, `provider`, `model`, `agent_profile` :
  `{export["unavailable_fields"]}`. Configuration/version par observation : inconnues.
- Contrôle HTTP authentifié `GET /api/v1/projects` : 200. Aux mêmes origine et
  credentials, `GET /api/v1/usage/summary` et `GET /api/v1/projects/{{id}}/mission` : 404.
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

## Levée du no-go (DEC-0221)

Le 19 octobre 2026, l'utilisateur a levé le no-go. L'historique est livré comme vue descriptive :
`GET /api/v1/usage/configuration-history` et l'onglet « Historique » du projet.
La population est TaskLaunch. Chaque taux affiche n, période, définition et couverture.
Les groupes ne sont ni classés ni comparables.
Les valeurs inconnues ou mixtes sont affichées telles quelles.
La vue rappelle aussi que des tests réussis ne garantissent pas la qualité.
Le rapprochement avec le ledger et AIWork sur un échantillon de production reste à relever.
Tant qu'il n'est pas fait, le critère correspondant de l'étape n'est pas coché.
Aucun minimum d'effectif n'est fixé.

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
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    folder = args.root / "docs" / "mission-control"
    snapshot_path = folder / "pilot-sample.json"
    report_path = folder / "pilot-data.md"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    metrics = summarize(snapshot)
    content = report(snapshot, metrics)
    if args.write_report:
        snapshot["metrics"] = metrics
        snapshot_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report_path.write_text(content, encoding="utf-8")
    if args.check:
        if metrics != snapshot.get("metrics") or content != report_path.read_text(encoding="utf-8"):
            raise SystemExit("P06 snapshot/report drift: regenerate and review")
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
